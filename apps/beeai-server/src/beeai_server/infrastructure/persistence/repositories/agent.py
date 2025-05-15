from uuid import UUID

from sqlalchemy import Table, Column, String, JSON, ForeignKey, MetaData, UUID as SqlUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select, insert, delete

from beeai_server.domain.models.agent import Agent, AgentRun
from beeai_server.domain.repositories.agent import IAgentRepository
from beeai_server.exceptions import EntityNotFoundError

metadata = MetaData()

agents_table = Table(
    "agents",
    metadata,
    Column("id", SqlUUID, primary_key=True),
    Column("name", String, unique=True, nullable=False),
    Column("description", String, nullable=True),
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
    def __init__(self, session: AsyncSession):
        self.session = session

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
                    "metadata": agent.metadata.model_dump(),
                }
                for agent in agents
            ]
        )
        await self.session.execute(query)

    async def get_agent(self, *, name: str) -> Agent:
        query = select(agents_table).where(agents_table.c.name == name)
        result = await self.session.execute(query)
        if not (row := result.fetchone()):
            raise EntityNotFoundError(entity="agent", id=name)

        return Agent.model_validate(dict(row))

    async def create_run(self, *, run: AgentRun) -> None:
        query = insert(agent_runs_table).values(id=run.id, acp_run_id=run.acp_run_id, agent_id=run.agent_id)
        await self.session.execute(query)

    async def delete_run(self, *, run_id: UUID) -> None:
        query = delete(agent_runs_table).where(agent_runs_table.c.id == run_id)
        await self.session.execute(query)
        await self.session.commit()

    async def find_by_run_id(self, *, run_id: UUID) -> Agent:
        result = await self.session.execute(
            select(agents_table)
            .join(agent_runs_table, agents_table.c.id == agent_runs_table.c.agent_id)
            .where(agent_runs_table.c.id == run_id)
        )
        if not (row := result.fetchone()):
            raise EntityNotFoundError(entity="agent_run", run_id=run_id)

        return Agent.model_validate(dict(row))
