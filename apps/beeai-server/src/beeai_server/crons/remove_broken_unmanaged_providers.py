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

import logging
from datetime import timedelta

from beeai_server.configuration import Configuration

from beeai_server.services.unit_of_work import IUnitOfWorkFactory
from beeai_server.utils.periodic import periodic
from kink import inject

logger = logging.getLogger(__name__)


@periodic(period=timedelta(seconds=5))
@inject
async def remove_broken_unmanaged_providers(configuration: Configuration, uow: IUnitOfWorkFactory):
    return
    # async with uow() as uow:
    # unmanaged_providers = [provider async for provider in await uow.providers.list() if not provider.managed]
    #
    # for loaded_provider in unmanaged_providers:
    #     if loaded_provider.state in {
    #         ProviderStatus.ready,
    #         ProviderStatus.error,
    #         ProviderStatus.running,
    #         LoadedProvider.last_error,
    #     }:
    #         try:
    #             with anyio.fail_after(delay=timedelta(seconds=30).total_seconds()):
    #                 async with loaded_provider.client() as client:
    #                     await client.get("agents")
    #         except Exception as ex:
    #             logger.error(
    #                 f"Provider {loaded_provider.id} failed to respond to ping in 30 seconds: {extract_messages(ex)}"
    #             )
    #             loaded_provider.state = ProviderStatus.error
    #             if not loaded_provider.provider.persistent:
    #                 await provider_container.remove(loaded_provider.provider)
