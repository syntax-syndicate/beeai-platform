from datetime import timedelta
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import Table, Column, String, UUID as SqlUUID, Integer, JSON, Row
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import select, insert, delete

from beeai_server.domain.models.provider import Provider
from beeai_server.domain.repositories.provider import IProviderRepository
from beeai_server.exceptions import EntityNotFoundError
from beeai_server.infrastructure.persistence.repositories.db_metadata import metadata

providers_table = Table(
    "providers",
    metadata,
    Column("id", SqlUUID, primary_key=True),
    Column("source", String(2048), nullable=False),
    Column("registry", String(2048), nullable=True),
    Column("env", JSON, nullable=False),
    Column("auto_stop_timeout_sec", Integer, nullable=False),
)


class SqlAlchemyProviderRepository(IProviderRepository):
    def __init__(self, connection: AsyncConnection):
        self.session = connection

    async def create(self, provider: Provider) -> None:
        query = insert(providers_table).values(
            {
                "id": provider.id,
                "auto_stop_timeout_sec": int(
                    provider.auto_stop_timeout.total_seconds() if provider.auto_stop_timeout else None
                ),
                "source": str(provider.source.root),
                "registry": str(provider.registry.root),
                "env": [env.model_dump(mode="json") for env in provider.env],
            }
        )
        await self.session.execute(query)

    def _to_provider(self, row: Row) -> Provider:
        return Provider.model_validate(
            {
                # ID is determined by source
                "source": row.source,
                "registry": row.registry,
                "auto_stop_timeout": timedelta(seconds=row.auto_stop_timeout_sec),
                "env": row.env,
            }
        )

    async def get(self, *, provider_id: UUID) -> Provider:
        query = select(providers_table).where(providers_table.c.id == provider_id)
        result = await self.session.execute(query)
        if not (row := result.fetchone()):
            raise EntityNotFoundError(entity="provider", id=provider_id)

        return self._to_provider(row)

    async def delete(self, *, provider_id: UUID) -> None:
        query = delete(providers_table).where(providers_table.c.id == provider_id)
        await self.session.execute(query)

    async def list(self) -> AsyncIterator[Provider]:
        async for row in await self.session.stream(select(providers_table)):
            yield self._to_provider(row)
