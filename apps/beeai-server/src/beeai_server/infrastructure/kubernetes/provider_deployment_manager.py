import base64
import hashlib
import json
import logging
import re
from asyncio import TaskGroup
from datetime import timedelta
from uuid import UUID

import kr8s
from exceptiongroup import suppress
from kr8s.objects import Deployment, Service, Secret, Pod
from pydantic import HttpUrl

from beeai_server.adapters.interface import IProviderDeploymentManager
from beeai_server.domain.models.provider import Provider, ProviderDeploymentState
from beeai_server.utils.logs_container import LogsContainer

logger = logging.getLogger(__name__)


class KubernetesProviderDeploymentManager(IProviderDeploymentManager):
    def _get_k8s_name(self, provider_id: UUID, kind: str | None = None):
        return f"beeai-provider-{provider_id}" + (f"-{kind}" if kind else "")

    def _get_provider_id_from_name(self, name: str, kind: str | None = None) -> UUID:
        pattern = rf"beeai-provider-([0-9a-f-]+)-{kind}$" if kind else r"beeai-provider-([0-9a-f-]+)$"
        if match := re.match(pattern, name):
            [provider_id] = match.groups()
            return UUID(provider_id)
        raise ValueError(f"Invalid provider name format: {name}")

    async def create_or_replace(self, *, provider: Provider, env: dict[str, str] | None = None):
        if not provider.managed:
            raise ValueError("Attempted to update provider not managed by Kubernetes")

        env = env or {}
        label = self._get_k8s_name(provider.id)
        service = Service(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {
                    "name": self._get_k8s_name(provider.id, "svc"),
                    "labels": {"app": label},
                },
                "spec": {
                    "type": "ClusterIP",
                    "ports": [{"port": 8000, "targetPort": 8000, "protocol": "TCP", "name": "http"}],
                    "selector": {"app": label},
                },
            }
        )
        env = {
            **provider.extract_env(env),
            "HOST": "0.0.0.0",
        }
        secret = Secret(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": self._get_k8s_name(provider.id, "secret"),
                    "labels": {"app": label},
                },
                "type": "Opaque",
                "data": {key: base64.b64encode(value.encode()).decode() for key, value in env.items()},
            }
        )

        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self._get_k8s_name(provider.id, "deploy"),
                "labels": {"app": label, "managedBy": "beeai-platform"},
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": label},
                },
                "template": {
                    "metadata": {"labels": {"app": label}},
                    "spec": {
                        "containers": [
                            {
                                "name": self._get_k8s_name(provider.id, "container"),
                                "image": str(provider.source.root),
                                "ports": [{"containerPort": 8000}],
                                "envFrom": [{"secretRef": {"name": self._get_k8s_name(provider.id, "secret")}}],
                            }
                        ]
                    },
                },
            },
        }
        combined_manifest = json.dumps(
            {"service": service.raw, "secret": secret.raw, "deployment": deployment_manifest}
        )
        deployment_hash = hashlib.sha256(combined_manifest.encode()).hexdigest()[:63]
        deployment_manifest["metadata"]["labels"]["deployment-hash"] = deployment_hash

        deployment = Deployment(deployment_manifest)
        try:
            existing_deployment = await Deployment.async_get(deployment.metadata.name)
            if existing_deployment.metadata.labels["deployment-hash"] == deployment_hash:
                if existing_deployment.replicas == 0:
                    await deployment.async_scale(1)
                return
            logger.info(f"Recreating deployment {deployment.metadata.name} due to configuration change")
            await self.delete(provider_id=provider.id)
        except kr8s.NotFoundError:
            logger.info(f"Creating new deployment {deployment.metadata.name}")
        try:
            await secret.async_create()
            await service.async_create()
            await deployment.async_create()
            await deployment.async_adopt(service)
            await deployment.async_adopt(secret)
        except Exception:
            # Try to revert changes already made
            with suppress(Exception):
                await secret.async_delete()
            with suppress(Exception):
                await service.async_delete()
            with suppress(Exception):
                await deployment.async_delete()
            raise

    async def delete(self, *, provider_id: UUID) -> None:
        with suppress(kr8s.NotFoundError):
            deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
            await deploy.async_delete(propagation_policy="Foreground", force=True)
            await deploy.async_wait({"delete"})

    async def scale_down(self, *, provider_id: UUID) -> None:
        deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
        await deploy.async_scale(0)

    async def scale_up(self, *, provider_id: UUID) -> None:
        deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
        await deploy.async_scale(1)

    async def wait_for_startup(self, *, provider_id: UUID, timeout: timedelta) -> None:
        deployment = await Deployment.async_get(name=self._get_k8s_name(provider_id, kind="deploy"))
        await deployment.async_wait("condition=Available", timeout=int(timeout.total_seconds()))

    async def state(self, *, provider_ids: list[UUID]) -> list[ProviderDeploymentState]:
        deployments = {
            self._get_provider_id_from_name(deployment.metadata.name, "deploy"): deployment
            async for deployment in kr8s.asyncio.get(
                kind="deployment",
                label_selector={"managedBy": "beeai-platform"},
            )
        }
        provider_ids_set = set(provider_ids)
        deployments = {provider_id: d for provider_id, d in deployments.items() if provider_id in provider_ids_set}
        states = []
        for provider_id in provider_ids:
            deployment = deployments.get(provider_id)
            if not deployment:
                state = ProviderDeploymentState.missing
            elif deployment.status.get("availableReplicas", 0) > 0:
                state = ProviderDeploymentState.running
            elif deployment.status.replicas == 0:
                state = ProviderDeploymentState.ready
            else:
                state = ProviderDeploymentState.starting
            states.append(state)
        return states

    async def get_provider_url(self, *, provider_id: UUID) -> HttpUrl:
        return HttpUrl(f"http://{self._get_k8s_name(provider_id, 'svc')}:8000")

    async def stream_logs(self, *, provider_id: UUID, logs_container: LogsContainer):
        deploy = await Deployment.async_get(self._get_k8s_name(provider_id, kind="deploy"))

        async def stream_logs(pod: Pod):
            async for line in pod.async_logs(follow=True):
                logs_container.add_stdout(f"{pod.name}: {line}")

        async with TaskGroup() as tg:
            for pod in await deploy.async_pods():
                tg.create_task(stream_logs(pod))
