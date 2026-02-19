import enum
from sqlalchemy import String, DateTime, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from core.db import Base
from sqlalchemy.orm import Mapped, mapped_column
import uuid

class ConsentStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"

class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(Enum(ConsentStatus), default=ConsentStatus.ACTIVE, nullable=False)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    revoked_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
