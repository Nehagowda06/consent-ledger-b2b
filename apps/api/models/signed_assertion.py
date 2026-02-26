import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, event, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.observability import (
    METRIC_APPEND_ONLY_VIOLATION_ATTEMPT,
    best_effort_system_event,
    increment_metric,
)


class SignedAssertion(Base):
    __tablename__ = "signed_assertions"
    __table_args__ = (
        Index("ix_signed_assertions_subject_type_subject_id", "subject_type", "subject_id"),
        Index("ix_signed_assertions_assertion_type", "assertion_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    identity_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("identity_keys.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assertion_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=False,
    )
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


@event.listens_for(SignedAssertion, "before_update", propagate=True)
def _prevent_update(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="signed_assertion_update")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="signed_assertions",
        payload={"reason": "update_attempt"},
    )
    raise ValueError("signed_assertions is append-only")


@event.listens_for(SignedAssertion, "before_insert", propagate=True)
def _enforce_tenant_lifecycle(_mapper, connection, target: SignedAssertion) -> None:
    row = connection.execute(
        sa.text(
            """
            SELECT t.is_active, t.lifecycle_state
            FROM identity_keys k
            JOIN tenants t ON t.id = k.owner_id
            WHERE k.id = :identity_key_id AND k.scope = 'tenant'
            LIMIT 1
            """
        ),
        {"identity_key_id": str(target.identity_key_id)},
    ).fetchone()
    if row and (not bool(row[0]) or str(row[1]) != "active"):
        raise ValueError("tenant is not allowed to write")


@event.listens_for(SignedAssertion, "before_delete", propagate=True)
def _prevent_delete(_mapper, _connection, _target) -> None:
    increment_metric(METRIC_APPEND_ONLY_VIOLATION_ATTEMPT, reason="signed_assertion_delete")
    best_effort_system_event(
        event_type="security.append_only_violation_attempt",
        resource_type="signed_assertions",
        payload={"reason": "delete_attempt"},
    )
    raise ValueError("signed_assertions is append-only")
