from typing import runtime_checkable, Protocol, AsyncIterator
from uuid import UUID

from beeai_server.domain.models.provider import Provider


@runtime_checkable
class IProviderRepository(Protocol):
    async def list(self) -> AsyncIterator[Provider]:
        yield ...

    async def create(self, *, provider: Provider) -> None: ...
    async def get(self, *, provider_id: UUID) -> Provider: ...
    async def delete(self, *, provider_id: UUID) -> None: ...
