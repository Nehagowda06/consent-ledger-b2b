from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from typing import Any

from core.db import SessionLocal
from core.logging_utils import log_structured

METRIC_SIGNATURE_VERIFICATION_FAILED = "security.signature_verification_failed"
METRIC_DELEGATION_VERIFICATION_FAILED = "security.delegation_verification_failed"
METRIC_TENANT_WRITE_DENIED = "security.tenant_write_denied"
METRIC_RATE_LIMIT_ENFORCED = "security.rate_limit_enforced"
METRIC_APPEND_ONLY_VIOLATION_ATTEMPT = "security.append_only_violation_attempt"
METRIC_UNEXPECTED_EXCEPTION = "runtime.unexpected_exception"


class _InMemoryCounters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)

    def increment(self, metric: str, value: int = 1) -> int:
        if value < 0:
            raise ValueError("counter increments must be non-negative")
        with self._lock:
            self._counters[metric] += value
            return self._counters[metric]

    def value(self, metric: str) -> int:
        with self._lock:
            return self._counters.get(metric, 0)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


COUNTERS = _InMemoryCounters()


def increment_metric(metric: str, *, request_id: str | None = None, reason: str | None = None) -> int:
    current = COUNTERS.increment(metric)
    log_structured(
        "metric.increment",
        metric=metric,
        value=current,
        request_id=request_id,
        reason=reason,
    )
    return current


def unexpected_exception_metric(error_class: str, *, request_id: str | None = None) -> int:
    base = increment_metric(METRIC_UNEXPECTED_EXCEPTION, request_id=request_id, reason=error_class)
    COUNTERS.increment(f"{METRIC_UNEXPECTED_EXCEPTION}.{error_class}")
    return base


def best_effort_system_event(
    *,
    event_type: str,
    tenant_id: uuid.UUID | str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    from core.system_events import record_system_event

    db = SessionLocal()
    try:
        record_system_event(
            db,
            event_type=event_type,
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
            fail_open=True,
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
