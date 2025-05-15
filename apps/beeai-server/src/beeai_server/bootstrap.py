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

import asyncio
import concurrent.futures
import logging
import shutil
from contextlib import AsyncExitStack

import anyio
import anyio.to_thread
from beeai_server.adapters.filesystem import (
    FilesystemEnvVariableRepository,
    FilesystemProviderRepository,
    FilesystemTelemetryRepository,
)
from beeai_server.adapters.interface import (
    IEnvVariableRepository,
    IProviderRepository,
    ITelemetryRepository,
)
from beeai_server.configuration import Configuration, get_configuration
from beeai_server.domain.collector.constants import TELEMETRY_BASE_CONFIG_PATH, TELEMETRY_BEEAI_CONFIG_PATH
from beeai_server.domain.provider.container import ProviderContainer
from beeai_server.domain.telemetry import TelemetryCollectorManager
from beeai_server.utils.periodic import register_all_crons
from kink import di

logger = logging.getLogger(__name__)


def copy_telemetry_config(config: Configuration):
    config.telemetry_config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(TELEMETRY_BASE_CONFIG_PATH, config.telemetry_config_dir / "base.yaml")
    shutil.copy(TELEMETRY_BEEAI_CONFIG_PATH, config.telemetry_config_dir / "beeai.yaml")


async def bootstrap_dependencies():
    """
    Disclaimer:
        contains blocking calls, but it's fine because this function should run only during startup
        it is async only because it needs to call other async code
    """

    di.clear_cache()
    di._aliases.clear()  # reset aliases

    di[Configuration] = config = get_configuration()

    copy_telemetry_config(config)

    di[IProviderRepository] = FilesystemProviderRepository(provider_config_path=config.provider_config_path)
    di[IEnvVariableRepository] = FilesystemEnvVariableRepository(env_variable_path=config.env_path)
    di[ITelemetryRepository] = FilesystemTelemetryRepository(
        telemetry_config_path=config.telemetry_config_dir / "telemetry.yaml"
    )
    di[TelemetryCollectorManager] = AsyncExitStack() if not config.collector_managed else TelemetryCollectorManager()
    di[ProviderContainer] = ProviderContainer(env_repository=di[IEnvVariableRepository])

    # Ensure cache directory
    await anyio.Path(config.cache_dir).mkdir(parents=True, exist_ok=True)
    register_all_crons()


def bootstrap_dependencies_sync():
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: asyncio.run(bootstrap_dependencies()))
        return future.result()
