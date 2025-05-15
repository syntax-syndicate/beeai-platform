from datetime import timedelta
from typing import overload

import httpx
from httpx import Response
from kink import inject
from pydantic import HttpUrl
from structlog.contextvars import bind_contextvars, unbind_contextvars

from beeai_server.adapters.interface import IProviderDeploymentManager, IProviderRepository
from beeai_server.custom_types import ID
from beeai_server.domain.models.provider import ProviderDeploymentStatus


@inject
class AcpProxyService:
    STARTUP_TIMEOUT = timedelta(minutes=5)

    def __init__(
        self, provider_deployment_manager: IProviderDeploymentManager, provider_repository: IProviderRepository
    ):
        self._deploy_manager = provider_deployment_manager
        self._provider_repository = provider_repository

    @overload
    async def get_proxy_client(self, *, agent_name: str, run_name: None = None) -> httpx.AsyncClient: ...
    @overload
    async def get_proxy_client(self, *, agent_name: None = None, run_id: ID) -> httpx.AsyncClient: ...
    async def get_proxy_client(self, *, agent_name: str = None, run_id: None = None) -> httpx.AsyncClient:
        try:
            if not (bool(agent_name) ^ bool(run_id)):
                raise ValueError("Exactly one of agent_name or run_id must be provided")
            async with self.uow:
                if agent_name:
                    provider = await self.uow.providers.get_by_agent_name(agent_name=agent_name)
                else:
                    provider = await self.uow.providers.get_by_run_id(run_id=run_id)
            bind_contextvars(provider=provider.id)
            provider_url = await self._deploy_manager.get_provider_url(provider_id=provider.id)
            match status := await self._deploy_manager.status(provider_id=provider.id):
                case ProviderDeploymentStatus.error:
                    raise RuntimeError("Provider is in an error state")
                case ProviderDeploymentStatus.running:
                    ...
                case ProviderDeploymentStatus.ready:
                    await self._deploy_manager.scale_up(provider_id=provider.id)
                    await self._deploy_manager.wait_for_startup(provider_id=provider.id, timeout=self.STARTUP_TIMEOUT)
                case ProviderDeploymentStatus.missing:
                    async with self.uow:
                        env = await self.uow.env.get_env()
                    await self._deploy_manager.create_or_replace(provider=provider, env=env)
                    await self._deploy_manager.wait_for_startup(provider_id=provider.id, timeout=self.STARTUP_TIMEOUT)
                case _:
                    raise ValueError(f"Unknown provider status: {status}")
            return self._get_client(provider_url)
        finally:
            unbind_contextvars("provider")

    def _get_client(self, url: HttpUrl) -> httpx.AsyncClient:
        async def _on_response(response: Response):
            if "Run-ID" in response.headers:
                async with self.uow:
                    await self.uow.providers.create_run(
                        ProviderRun(acp_run_id=response.headers["Run-ID"], provider_id=provider.id)
                    )
            return response

        return httpx.AsyncClient(base_url=str(url), event_hooks={"response": [_on_response]}, timeout=None)
