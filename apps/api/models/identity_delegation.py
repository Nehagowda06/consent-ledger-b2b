import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, event, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.observability import (
    METRIC_APPEND_ONLY_VIOLATION_ATTEMPT,
    best_effort_system_event,
    increment_metric,
)


class IdentityDelegation(Base):
    __tablename__ = "identity_delegations"
    __table_args__ = (
        CheckConstraint("parent_identity_key_id <> child_identity_key_id", name="ck_identity_delegations_parent_child_diff"),
        Index("ix_identity_delegations_parent_identity_key_id", "parent_identity_key_id"),
        Index("ix_identity_delegations_child_identity_key_id", "child_identity_key_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_identity_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    child_identity_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delegation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@event.listens_for(IdentityDelegation, "before_insert", propagate=True)
def _enforce_tenant_lifecycle(_mapper, connection, target: IdentityDelegation) -> None:
    rows = connection.execute(
        sa.text(
            """
            SELECT t.is_active, t.lifecycle_state
            FROM identity_keys k
            JOIN tenants t ON t.id = k.owner_id
            WHERE k.scope = 'tenant'
              AND (k.id = :parent_identity_key_id OR k.id = :child_identity_key_id)
            """
        ),
        {
            "parent_identity_key_id": str(target.parent_identity_key_id),
            "child_identity_key_id": str(target.child_identity_key_id),
        },
    ).fetchall()
    for is_active, lifecycle_state in rows:
        if not bool(is_active) or str(lifecycle_state) != "active":
            raise ValueError("tenant is not allowed to write")


@event.listens_for(IdentityDelegation, "before_update", propagate=True)
def _prevent_update(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="identity_delegation_update")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="identity_delegations",
        payload={"reason": "update_attempt"},
    )
    raise ValueError("identity_delegations is append-only")


@event.listens_for(IdentityDelegation, "before_delete", propagate=True)
def _prevent_delete(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="identity_delegation_delete")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="identity_delegations",
        payload={"reason": "delete_attempt"},
    )
    raise ValueError("identity_delegations is append-only")
