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

from contextlib import AsyncExitStack
from typing import Any

import fastapi
import fastapi.responses
import httpx
from acp_sdk.models import (
    AgentName,
    RunCancelResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunId,
    RunReadResponse,
    RunResumeRequest,
    RunResumeResponse,
)

from beeai_server.api.schema.acp import AgentsListResponse, AgentReadResponse
from beeai_server.api.routes.dependencies import AcpProxyServiceDependency

router = fastapi.APIRouter()


@router.get("/agents")
async def list_agents(acp_service: AcpProxyServiceDependency) -> AgentsListResponse:
    return AgentsListResponse(agents=await acp_service.list_agents())


@router.get("/agents/{name}")
async def read_agent(name: AgentName, acp_service: AcpProxyServiceDependency) -> AgentReadResponse:
    return AgentReadResponse.model_validate(await acp_service.get_agent_by_name(name))


async def send_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    json: dict[str, Any] | None = None,
) -> fastapi.responses.Response:
    exit_stack = AsyncExitStack()

    try:
        client = await exit_stack.enter_async_context(client)
        response: httpx.Response = await exit_stack.enter_async_context(client.stream(method, url, json=json))

        async def stream_fn():
            try:
                async for event in response.stream:
                    yield event
            finally:
                await exit_stack.pop_all().aclose()

        if response.headers["content-type"].startswith("text/event-stream"):
            return fastapi.responses.StreamingResponse(
                stream_fn(),
                status_code=response.status_code,
                headers=response.headers,
                media_type=response.headers["content-type"],
            )
        else:
            try:
                await response.aread()
                return fastapi.responses.Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response.headers,
                    media_type=response.headers["content-type"],
                )
            finally:
                await exit_stack.pop_all().aclose()
    except BaseException:
        await exit_stack.pop_all().aclose()
        raise


@router.post("/runs")
async def create_run(request: RunCreateRequest, acp_service: AcpProxyServiceDependency) -> RunCreateResponse:
    client = await acp_service.get_proxy_client(agent_name=request.agent_name)
    return await send_request(client, "POST", "/runs", request.model_dump(mode="json"))


@router.get("/runs/{run_id}")
async def read_run(run_id: RunId, acp_service: AcpProxyServiceDependency) -> RunReadResponse:
    client = await acp_service.get_proxy_client(run_id=run_id)
    return await send_request(client, "GET", f"/runs/{run_id}")


@router.post("/runs/{run_id}")
async def resume_run(
    run_id: RunId, request: RunResumeRequest, acp_service: AcpProxyServiceDependency
) -> RunResumeResponse:
    client = await acp_service.get_proxy_client(run_id=run_id)
    return await send_request(client, "POST", f"/runs/{run_id}", request.model_dump(mode="json"))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: RunId, acp_service: AcpProxyServiceDependency) -> RunCancelResponse:
    client = await acp_service.get_proxy_client(run_id=run_id)
    return await send_request(client, "POST", f"/runs/{run_id}/cancel")
