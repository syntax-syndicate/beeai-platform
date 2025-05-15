from pydantic import BaseModel


class UpdateTelemetryConfigRequest(BaseModel):
    sharing_enabled: bool
