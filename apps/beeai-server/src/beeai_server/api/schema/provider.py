from pydantic import BaseModel, Field

from beeai_server.custom_types import ID
from beeai_server.domain.models.provider import ProviderLocation, NetworkProviderLocation


class CreateManagedProviderRequest(BaseModel):
    location: ProviderLocation


class RegisterUnmanagedProviderRequest(BaseModel):
    location: NetworkProviderLocation
    id: ID | None = Field(default=None, deprecated=True)
