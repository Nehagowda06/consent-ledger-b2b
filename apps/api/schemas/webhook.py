from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, HttpUrl


class WebhookCreate(BaseModel):
    url: HttpUrl
    label: str | None = None
    enabled: bool = True


class WebhookPatch(BaseModel):
    url: HttpUrl | None = None
    label: str | None = None
    enabled: bool | None = None


class WebhookOut(BaseModel):
    id: UUID
    url: str
    label: str | None
    enabled: bool
    secret_masked: str
    created_at: datetime
    updated_at: datetime


class WebhookCreateOut(WebhookOut):
    secret: str


class DeliveryOut(BaseModel):
    id: UUID
    endpoint_id: UUID
    event_type: str
    status: str
    attempt_count: int
    last_attempt_at: datetime | None
    next_attempt_at: datetime | None
    last_error: str | None
    created_at: datetime
