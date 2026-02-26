import logging
import time
import uuid
from typing import Any

from fastapi import Request

from core.config import get_settings


logger = logging.getLogger("consent_ledger.api")
ALLOWED_LOG_FIELDS = {
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "event_type",
    "metric",
    "value",
    "reason",
    "error_class",
    "failure_class",
    "tenant_id",
    "resource_type",
    "resource_id",
    "api_version",
    "check",
    "result",
}


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _safe_value(value: Any) -> str:
    text = str(value)
    lowered = text.lower()
    forbidden_markers = ("secret", "private_key", "authorization", "bearer ", "api_key", "password")
    if any(marker in lowered for marker in forbidden_markers):
        return "[REDACTED]"
    return text


def log_structured(event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if key not in ALLOWED_LOG_FIELDS:
            continue
        if value is None:
            continue
        parts.append(f"{key}={_safe_value(value)}")
    logger.info(" ".join(parts))


def request_id_from_request(request: Request) -> str:
    incoming = request.headers.get("X-Request-Id")
    if incoming and incoming.strip():
        return incoming.strip()
    return str(uuid.uuid4())


def log_request(request_id: str, method: str, path: str, status_code: int, elapsed_ms: float) -> None:
    # Intentionally avoids logging auth headers, API keys, or payloads.
    log_structured(
        "request.completed",
        request_id=request_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=f"{elapsed_ms:.2f}",
    )


def monotonic_ms() -> float:
    return time.perf_counter() * 1000.0
