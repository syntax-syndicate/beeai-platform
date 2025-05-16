from datetime import timedelta
from typing import overload
from uuid import UUID

import httpx
from acp_sdk import ACPError, Error, ErrorCode
from httpx import Response
from kink import inject
from pydantic import HttpUrl
from structlog.contextvars import bind_contextvars, unbind_contextvars

from beeai_server.adapters.interface import IProviderDeploymentManager
from beeai_server.domain.models.agent import AgentRun, Agent
from beeai_server.domain.models.provider import ProviderDeploymentState
from beeai_server.exceptions import EntityNotFoundError
from beeai_server.services.unit_of_work import IUnitOfWorkFactory


@inject
class AcpProxyService:
    STARTUP_TIMEOUT = timedelta(minutes=5)

    def __init__(
        self,
        provider_deployment_manager: IProviderDeploymentManager,
        uow: IUnitOfWorkFactory,
    ):
        self._deploy_manager = provider_deployment_manager
        self._uow = uow

    @overload
    async def get_proxy_client(self, *, agent_name: str, run_id: None = None) -> httpx.AsyncClient: ...
    @overload
    async def get_proxy_client(self, *, agent_name: None = None, run_id: UUID) -> httpx.AsyncClient: ...
    async def get_proxy_client(self, *, agent_name: str = None, run_id: None = None) -> httpx.AsyncClient:
        try:
            if not (bool(agent_name) ^ bool(run_id)):
                raise ValueError("Exactly one of agent_name or run_id must be provided")
            async with self._uow() as uow:
                if agent_name:
                    agent = await uow.agents.get_agent_by_name(name=agent_name)
                else:
                    agent = await uow.agents.find_by_run_id(run_id=run_id)
                provider = await uow.providers.get(provider_id=agent.provider_id)
            bind_contextvars(provider=provider.id)
            provider_url = await self._deploy_manager.get_provider_url(provider_id=provider.id)
            [state] = await self._deploy_manager.state(provider_ids=[provider.id])
            match state:
                case ProviderDeploymentState.error:
                    raise RuntimeError("Provider is in an error state")
                case ProviderDeploymentState.running:
                    ...
                case ProviderDeploymentState.ready:
                    await self._deploy_manager.scale_up(provider_id=provider.id)
                    await self._deploy_manager.wait_for_startup(provider_id=provider.id, timeout=self.STARTUP_TIMEOUT)
                case ProviderDeploymentState.missing:
                    async with self._uow() as uow:
                        env = await uow.env.get_all()
                    await self._deploy_manager.create_or_replace(provider=provider, env=env)
                    await self._deploy_manager.wait_for_startup(provider_id=provider.id, timeout=self.STARTUP_TIMEOUT)
                case _:
                    raise ValueError(f"Unknown provider state: {state}")
            return self._get_client(provider_url, agent=agent if agent_name else None)
        except EntityNotFoundError as ex:
            if ex.entity == "agent":
                raise ACPError(error=Error(code=ErrorCode.NOT_FOUND, message=f"Agent '{ex.id}' not found")) from ex
            raise
        finally:
            unbind_contextvars("provider")

    def _get_client(self, url: HttpUrl, agent: Agent | None = None) -> httpx.AsyncClient:
        event_hooks = {}

        if agent:

            async def _on_response(response: Response):
                if "Run-ID" in response.headers:
                    async with self._uow() as uow:
                        await uow.agents.create_run(
                            run=AgentRun(acp_run_id=response.headers["Run-ID"], agent_id=agent.id)
                        )
                        await uow.commit()
                return response

            event_hooks["response"] = [_on_response]
        return httpx.AsyncClient(base_url=str(url), event_hooks=event_hooks, timeout=None)

    async def list_agents(self) -> list[Agent]:
        async with self._uow() as uow:
            return [agent async for agent in uow.agents.list()]

    async def get_agent_by_name(self, name: str) -> Agent:
        async with self._uow() as uow:
            return await uow.agents.get_agent_by_name(name=name)
