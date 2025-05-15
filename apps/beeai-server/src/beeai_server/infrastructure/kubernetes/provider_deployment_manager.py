import hashlib
import json
import logging
from datetime import timedelta

import kr8s
from exceptiongroup import suppress
from kr8s.objects import Deployment, Service, Secret
from pydantic import HttpUrl

from beeai_server.adapters.interface import IProviderDeploymentManager
from beeai_server.custom_types import ID
from beeai_server.domain.models.provider import Provider, ProviderDeploymentStatus

logger = logging.getLogger(__name__)


class KubernetesProviderDeploymentManager(IProviderDeploymentManager):
    def _get_k8s_name(self, provider_id: Provider, kind: str | None = None):
        return f"beeai-provider-{provider_id}" + f"-{kind}" if kind else ""

    async def create_or_replace(self, *, provider: Provider, env: dict[str, str] | None = None):
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
        secret = Secret(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "name": self._get_k8s_name(provider.id, "secret"),
                "type": "Opaque",
                "data": provider.extract_env(env),
            }
        )

        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self._get_k8s_name(provider, "deploy"),
                "labels": {"app": label},
            },
            "spec": {
                "replicas": 1,
                "selector": {
                    "matchLabels": {"app": label},
                    "template": {"metadata": {"labels": {"app": label}}},
                    "spec": {
                        "containers": [
                            {
                                "name": self._get_k8s_name(provider, "container"),
                                "image": str(provider.image_id),
                                "ports": [{"containerPort": 8000}],
                                "envFrom": [{"secretRef": {"name": "beeai-provider-secret"}}],
                            }
                        ]
                    },
                },
            },
        }
        combined_manifest = json.dumps(
            {"service": service.raw, "secret": secret.raw, "deployment": deployment_manifest}
        )
        deployment_hash = hashlib.sha256(combined_manifest.encode()).hexdigest()
        deployment_manifest["metadata"]["labels"]["deployment-hash"] = deployment_hash

        deployment = Deployment(deployment_manifest)
        url = HttpUrl(f"http://{self._get_k8s_name(provider.id, 'svc')}")
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
        await secret.async_create()
        await service.async_create()
        await deployment.async_create()
        await deployment.async_adopt(service)
        await deployment.async_adopt(secret)

    async def delete(self, *, provider_id: ID) -> None:
        with suppress(kr8s.NotFoundError):
            deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
            await deploy.async_delete(propagation_policy="Foreground", force=True)
            await deploy.async_wait({"delete"})

    async def scale_down(self, *, provider_id: ID) -> None:
        deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
        await deploy.async_scale(0)

    async def scale_up(self, *, provider_id: ID) -> None:
        deploy = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
        await deploy.async_scale(1)

    async def wait_for_startup(self, *, provider_id: ID, timeout: timedelta) -> None:
        deployment = await Deployment.async_get(name=self._get_k8s_name(provider_id, kind="deploy"))
        await deployment.async_wait("condition=Available", timeout=int(timeout.total_seconds()))

    async def status(self, *, provider_id: ID) -> ProviderDeploymentStatus:
        with suppress(kr8s.NotFoundError):
            deployment = await Deployment.async_get(name=self._get_k8s_name(provider_id, "deploy"))
            if deployment.status.availableReplicas > 0:
                return ProviderDeploymentStatus.running
            elif deployment.status.replicas == 0:
                return ProviderDeploymentStatus.ready
            else:
                return ProviderDeploymentStatus.starting
        return ProviderDeploymentStatus.missing

    async def get_provider_url(self, *, provider_id: ID) -> HttpUrl:
        return HttpUrl(f"http://{self._get_k8s_name(provider_id, 'svc')}")
