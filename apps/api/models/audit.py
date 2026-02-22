import uuid

from sqlalchemy import Column, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID

from core.db import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consent_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False, default="system", server_default=text("'system'"))
    at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())