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

import functools
import logging
import math
from collections import ChainMap
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import AsyncIterator, Callable, TypeVar, Mapping, Self

import httpx
from cachetools import TTLCache
from httpx import Response

from beeai_server.adapters.interface import IEnvVariableRepository
from beeai_server.domain.models.provider import BaseProvider, ProviderErrorMessage
from beeai_server.domain.models.agent import EnvVar, Agent
from beeai_server.utils.logs_container import LogsContainer
from pydantic import BaseModel
from structlog.contextvars import bind_contextvars, unbind_contextvars

logger = logging.getLogger(__name__)

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


def bind_logging_context(method: Callable) -> Callable:
    @functools.wraps(method)
    async def _fn(self: "LoadedProvider", *args, **kwargs):
        bind_contextvars(provider=self.provider.location)
        try:
            return await method(self, *args, **kwargs)
        finally:
            unbind_contextvars("provider")

    return _fn


class LoadedProvider:
    last_error: ProviderErrorMessage | None = None
    provider: BaseProvider
    id: str
    missing_configuration: list[EnvVar] = []
    runs: Mapping[str, Self]

    def __init__(self, provider: BaseProvider, env: dict[str, str], autostart=True) -> None:
        self.provider = provider
        self.env = env
        self.id = provider.id
        self.logs_container = LogsContainer()
        self.requests = {}
        self.runs = TTLCache(maxsize=math.inf, ttl=timedelta(minutes=30).total_seconds())
        self._base_url: str | None = None
        self.agents = [
            Agent.model_validate(
                {
                    "name": agent.name,
                    "description": agent.description,
                    "metadata": {**agent.metadata.model_dump(), "provider": self.id},
                }
            )
            for agent in self.provider.manifest.agents
        ]

    @asynccontextmanager
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        bind_contextvars(provider=self.id)

        async def _on_response(response: Response):
            if "Run-ID" in response.headers:
                self.runs[response.headers["Run-ID"]] = self
            return response

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, event_hooks={"response": [_on_response]}, timeout=None
            ) as client:
                yield client
        finally:
            unbind_contextvars("provider")

    def _with_id(self, objects: list[BaseModelT]) -> list[BaseModelT]:
        for obj in objects:
            obj.provider = self.id
        return objects


class ProviderContainer:
    """
    Manage group of LoadedProvider instances:
      - react to changes in provider repository - add or remove providers as necessary
    """

    def __init__(self, env_repository: IEnvVariableRepository):
        self.loaded_providers: dict[str, LoadedProvider] = {}
        self._env_repository = env_repository
        self._env: dict[str, str] | None = None

    def get_provider_by_agent(self, agent_name: str) -> LoadedProvider:
        providers = [
            loaded_provider
            for loaded_provider in self.loaded_providers.values()
            if agent_name in {a.name for a in loaded_provider.agents}
        ]
        if not providers:
            raise ValueError(f"Agent {agent_name} not found")
        return providers[0]

    def get_provider_by_run(self, run_id: str) -> LoadedProvider:
        provider = ChainMap(*(provider.runs for provider in self.loaded_providers.values())).get(run_id, None)
        if provider:
            return provider
        raise ValueError(f"Run {run_id} not found")

    async def add(self, provider: BaseProvider):
        env = await self._env_repository.get_all()
        self.loaded_providers[provider.id] = LoadedProvider(provider, env=provider.extract_env(env))

    async def remove(self, provider: BaseProvider):
        self.loaded_providers.pop(provider.id)

    async def add_or_replace(self, provider: BaseProvider):
        if provider.id in self.loaded_providers:
            await self.remove(provider)
        await self.add(provider)
