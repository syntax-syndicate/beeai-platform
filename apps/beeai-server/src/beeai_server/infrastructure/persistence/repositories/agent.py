from typing import AsyncIterable
from uuid import UUID

from sqlalchemy import Table, Column, String, JSON, ForeignKey, UUID as SqlUUID, Text, Select, Row
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import select, insert, delete

from beeai_server.domain.models.agent import Agent, AgentRun
from beeai_server.domain.repositories.agent import IAgentRepository
from beeai_server.exceptions import EntityNotFoundError
from beeai_server.infrastructure.persistence.repositories.db_metadata import metadata

agents_table = Table(
    "agents",
    metadata,
    Column("id", SqlUUID, primary_key=True),
    Column("name", String(256), unique=True, nullable=False),
    Column("description", Text, nullable=True),
    Column("provider_id", ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
    Column("metadata", JSON, nullable=False),
)

agent_runs_table = Table(
    "agent_runs",
    metadata,
    Column("id", SqlUUID, primary_key=True),
    Column("acp_run_id", SqlUUID, nullable=False),
    Column("agent_id", SqlUUID, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
)


class SqlAlchemyAgentRepository(IAgentRepository):
    def __init__(self, connection: AsyncConnection):
        self.connection = connection

    async def bulk_create(self, agents: list[Agent]) -> None:
        if not agents:
            return
        query = insert(agents_table).values(
            [
                {
                    "id": agent.id,
                    "name": agent.name,
                    "description": agent.description,
                    "provider_id": agent.provider_id,
                    "metadata": agent.metadata.model_dump(mode="json"),
                }
                for agent in agents
            ]
        )
        await self.connection.execute(query)

    async def list(self) -> AsyncIterable[Agent]:
        async for row in await self.connection.stream(select(agents_table)):
            yield self._to_agent(row)

    async def get_agent(self, *, agent_id: UUID) -> Agent:
        return await self._get_one(agents_table.select().where(agents_table.c.id == agent_id), id=agent_id)

    async def get_agent_by_name(self, *, name: str) -> Agent:
        return await self._get_one(agents_table.select().where(agents_table.c.name == name), id=name)

    def _to_agent(self, row: Row) -> Agent:
        return Agent.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "provider_id": row.provider_id,
                "metadata": row.metadata,
            }
        )

    async def _get_one(self, query: Select, id: str):
        result = await self.connection.execute(query)
        if not (row := result.fetchone()):
            raise EntityNotFoundError(entity="agent", id=id)

        return self._to_agent(row)

    async def create_run(self, *, run: AgentRun) -> None:
        query = insert(agent_runs_table).values(id=run.id, acp_run_id=run.acp_run_id, agent_id=run.agent_id)
        await self.connection.execute(query)

    async def delete_run(self, *, run_id: UUID) -> None:
        query = delete(agent_runs_table).where(agent_runs_table.c.id == run_id)
        await self.connection.execute(query)

    async def find_by_run_id(self, *, run_id: UUID) -> Agent:
        result = await self.connection.execute(
            select(agents_table)
            .join(agent_runs_table, agents_table.c.id == agent_runs_table.c.agent_id)
            .where(agent_runs_table.c.id == run_id)
        )
        if not (row := result.fetchone()):
            raise EntityNotFoundError(entity="agent_run", id=run_id)

        return self._to_agent(row)
