from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
import uuid

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from core.db import SessionLocal
from core.observability import unexpected_exception_metric
from core.system_events import record_system_event


class FailureClass(StrEnum):
    DB_UNAVAILABLE = "db.unavailable"
    DB_CONSTRAINT_VIOLATION = "db.constraint_violation"
    SIGNATURE_FAILED = "signature.failed"
    SERIALIZATION_FAILED = "serialization.failed"
    UNEXPECTED_EXCEPTION = "unexpected.exception"


@dataclass(frozen=True)
class FailurePolicy:
    failure_class: FailureClass
    http_status: int
    fail_closed: bool


def classify_failure(exc: Exception) -> FailureClass:
    if isinstance(exc, IntegrityError):
        return FailureClass.DB_CONSTRAINT_VIOLATION
    if isinstance(exc, (OperationalError, DBAPIError)):
        return FailureClass.DB_UNAVAILABLE

    lowered = str(exc).lower()
    if "signature" in lowered:
        return FailureClass.SIGNATURE_FAILED
    if "serialize" in lowered or "serializ" in lowered or "json" in lowered:
        return FailureClass.SERIALIZATION_FAILED
    return FailureClass.UNEXPECTED_EXCEPTION


def failure_policy(exc: Exception) -> FailurePolicy:
    failure_class = classify_failure(exc)
    if failure_class == FailureClass.DB_UNAVAILABLE:
        return FailurePolicy(failure_class=failure_class, http_status=503, fail_closed=True)
    if failure_class == FailureClass.DB_CONSTRAINT_VIOLATION:
        return FailurePolicy(failure_class=failure_class, http_status=409, fail_closed=True)
    if failure_class in {FailureClass.SIGNATURE_FAILED, FailureClass.SERIALIZATION_FAILED}:
        return FailurePolicy(failure_class=failure_class, http_status=422, fail_closed=True)
    return FailurePolicy(failure_class=failure_class, http_status=500, fail_closed=True)


def failure_event_type(operation: str) -> str:
    return f"{operation}.failed"


def record_operation_failure(
    *,
    operation: str,
    exc: Exception,
    db: Session | None = None,
    tenant_id: uuid.UUID | str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort failure telemetry emitted after rollback boundaries."""
    payload = {
        "operation": operation,
        "failure_class": classify_failure(exc).value,
        "error_type": exc.__class__.__name__,
    }
    if extra_payload:
        payload.update(extra_payload)
    if payload["failure_class"] == FailureClass.UNEXPECTED_EXCEPTION.value:
        unexpected_exception_metric(payload["error_type"], request_id=payload.get("request_id"))

    session = db if db is not None else SessionLocal()
    owns_session = db is None
    try:
        record_system_event(
            session,
            event_type=failure_event_type(operation),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            fail_open=True,
        )
        if hasattr(session, "commit"):
            session.commit()
    except Exception:
        if hasattr(session, "rollback"):
            session.rollback()
    finally:
        if owns_session:
            session.close()
