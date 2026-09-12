import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID | None
    channel_id: uuid.UUID | None
    action_type: str
    provider: str | None
    content_id: str | None
    result: str
    failure_reason: str | None
