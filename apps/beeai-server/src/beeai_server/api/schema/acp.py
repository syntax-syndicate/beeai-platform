from acp_sdk import AgentsListResponse as AcpAgentsListResponse

from beeai_server.domain.models.agent import Agent


class AgentsListResponse(AcpAgentsListResponse):
    agents: list[Agent]


class AgentReadResponse(Agent):
    pass
