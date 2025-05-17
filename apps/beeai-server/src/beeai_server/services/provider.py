# Copyright 2025 © BeeAI a Series of LF Projects, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable
from uuid import UUID

from fastapi import HTTPException
from kink import inject
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND

from beeai_server.adapters.interface import (
    IProviderDeploymentManager,
)
from beeai_server.domain.models.provider import (
    ProviderLocation,
    Provider,
    ProviderWithState,
)
from beeai_server.domain.models.registry import RegistryLocation
from beeai_server.exceptions import ManifestLoadError
from beeai_server.services.unit_of_work import IUnitOfWorkFactory
from beeai_server.utils.logs_container import LogsContainer

logger = logging.getLogger(__name__)


@inject
class ProviderService:
    def __init__(
        self,
        deployment_manager: IProviderDeploymentManager,
        uow: IUnitOfWorkFactory,
    ):
        self._uow = uow
        self._deployment_manager = deployment_manager

    async def create_provider(
        self, *, location: ProviderLocation, registry: RegistryLocation | None = None
    ) -> ProviderWithState:
        try:
            agents = await location.load_agents(provider_id=location.provider_id)
            provider_env = {env.name: env for agent in agents for env in agent.metadata.env}
            provider = Provider(source=location, registry=registry, env=list(provider_env.values()))
        except ValueError as ex:
            raise ManifestLoadError(location=location, message=str(ex), status_code=HTTP_400_BAD_REQUEST) from ex
        except Exception as ex:
            raise ManifestLoadError(location=location, message=str(ex)) from ex

        async with self._uow() as uow:
            env = await uow.env.get_all()
            await uow.providers.create(provider=provider)
            await uow.agents.bulk_create(agents)
            if provider.managed:
                await self._deployment_manager.create_or_replace(provider=provider, env=env)
            await uow.commit()
        [provider_response] = await self._get_providers_with_state(providers=[provider])
        return provider_response

    async def preview_provider(self, location: ProviderLocation):
        try:
            agents = await location.load_agents(provider_id=location.provider_id)
            provider_env = {env.name: env for agent in agents for env in agent.metadata.env}
            provider = Provider(source=location, env=list(provider_env.values()))
            [provider_response] = await self._get_providers_with_state(providers=[provider])
            return provider_response
        except ValueError as ex:
            raise ManifestLoadError(location=location, message=str(ex), status_code=HTTP_400_BAD_REQUEST) from ex
        except Exception as ex:
            raise ManifestLoadError(location=location, message=str(ex)) from ex

    async def _get_providers_with_state(self, providers: list[Provider]) -> list[ProviderWithState]:
        result_providers = []

        async with self._uow() as uow:
            env = await uow.env.get_all()

        provider_states = await self._deployment_manager.state(provider_ids=[provider.id for provider in providers])

        for provider, state in zip(providers, provider_states):
            result_providers.append(
                ProviderWithState(
                    **provider.model_dump(),
                    state=state,
                    missing_configuration=[var for var in provider.check_env(env, raise_error=False) if var.required],
                )
            )
        return result_providers

    async def delete_provider(self, *, provider_id: UUID):
        async with self._uow() as uow:
            await uow.providers.delete(provider_id=provider_id)
            await self._deployment_manager.delete(provider_id=provider_id)

    async def list_providers(self) -> list[ProviderWithState]:
        async with self._uow() as uow:
            return await self._get_providers_with_state(providers=[p async for p in uow.providers.list()])

    async def get_provider(self, provider_id: UUID) -> ProviderWithState:
        providers = [provider for provider in await self.list_providers() if provider.id == provider_id]
        if not providers:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail=f"Provider with ID: {str(provider_id)} not found"
            )
        return providers[0]

    async def stream_logs(self, provider_id: UUID) -> Callable[..., AsyncIterator[str]]:
        logs_container = LogsContainer()

        logs_task = asyncio.create_task(
            self._deployment_manager.stream_logs(provider_id=provider_id, logs_container=logs_container)
        )

        async def logs_iterator() -> AsyncIterator[str]:
            async with logs_container.stream() as stream:
                async for message in stream:
                    yield json.dumps(message.model_dump(mode="json"))

        return logs_iterator
