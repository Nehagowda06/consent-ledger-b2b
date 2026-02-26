import enum
import uuid

from sqlalchemy import Boolean, DateTime, Enum, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class TenantLifecycleState(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    lifecycle_state: Mapped[TenantLifecycleState] = mapped_column(
        Enum(
            TenantLifecycleState,
            name="tenantlifecyclestate",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=TenantLifecycleState.ACTIVE,
        server_default=TenantLifecycleState.ACTIVE.value,
    )
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    @property
    def can_write(self) -> bool:
        lifecycle = self.lifecycle_state
        lifecycle_active = lifecycle in (None, TenantLifecycleState.ACTIVE, TenantLifecycleState.ACTIVE.value)
        return bool(self.is_active) and lifecycle_active
