from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from acp_sdk.models import Agent as AcpAgentOriginal, Metadata as AcpMetadataOriginal


class EnvVar(BaseModel):
    name: str
    description: str | None = None
    required: bool = False


class AcpMetadata(AcpMetadataOriginal):
    env: list[EnvVar] = Field(default_factory=list, description="For configuration -- passed to the process")
    ui: dict[str, Any] | None = None


class Agent(AcpAgentOriginal, extra="allow"):
    metadata: AcpMetadata = AcpMetadata()
    provider_id: UUID


class AgentRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    acp_run_id: UUID
    agent_id: UUID
