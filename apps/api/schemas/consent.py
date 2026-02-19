from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class ConsentCreate(BaseModel):
    subject_id: str
    purpose: str

class ConsentOut(BaseModel):
    id: UUID
    subject_id: str
    purpose: str
    status: str
    created_at: datetime
    updated_at: datetime
    revoked_at: Optional[datetime] = None

    class Config:
        from_attributes = True
