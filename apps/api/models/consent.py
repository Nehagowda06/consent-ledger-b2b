import enum
from sqlalchemy import String, DateTime, Enum, ForeignKey, UniqueConstraint, text
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
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "subject_id",
            "purpose",
            name="uq_consents_tenant_subject_purpose",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
        server_default=text("'00000000-0000-0000-0000-000000000001'"),
    )
    subject_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(Enum(ConsentStatus), default=ConsentStatus.ACTIVE, nullable=False)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    revoked_at: Mapped["DateTime | None"] = mapped_column(DateTime(timezone=True), nullable=True)
