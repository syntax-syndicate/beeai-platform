from pydantic import BaseModel


class UpdateVariablesRequest(BaseModel):
    env: dict[str, str | None]


class ListVariablesSchema(BaseModel):
    env: dict[str, str]
