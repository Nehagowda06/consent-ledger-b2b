from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TenantCreateIn(BaseModel):
    name: str


class TenantOut(BaseModel):
    id: UUID
    name: str
    is_active: bool
    created_at: datetime


class ApiKeyCreateIn(BaseModel):
    label: str = "admin-created-key"


class ApiKeyCreateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    label: str
    created_at: datetime
    api_key: str
