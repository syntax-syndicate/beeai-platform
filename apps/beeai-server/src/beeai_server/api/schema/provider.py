from pydantic import BaseModel

from beeai_server.domain.models.provider import ProviderLocation


class CreateProviderRequest(BaseModel):
    location: ProviderLocation
