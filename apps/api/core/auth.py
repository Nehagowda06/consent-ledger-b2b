import hmac
from typing import Protocol

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.api_keys import hash_api_key
from core.config import get_settings
from core.deps import get_db
from core.failure_modes import classify_failure
from core.logging_utils import log_structured
from core.observability import (
    METRIC_RATE_LIMIT_ENFORCED,
    METRIC_TENANT_WRITE_DENIED,
    increment_metric,
)
from core.rate_limit import SQLiteRateLimiter
from core.system_events import record_system_event
from models.api_key import ApiKey
from models.tenant import Tenant, TenantLifecycleState


AUTH_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid authentication credentials",
)


class RateLimitHook(Protocol):
    def allow(self, identity: str) -> bool: ...
settings = get_settings()
RATE_LIMITER: RateLimitHook = SQLiteRateLimiter(
    db_path=settings.rate_limit_db_path,
    limit_per_minute=settings.api_key_rate_limit_per_min,
)
bearer_scheme = HTTPBearer(auto_error=False)


def extract_api_key(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = None,
) -> str | None:
    if bearer and hasattr(bearer, "scheme") and bearer.scheme.lower() == "bearer" and bearer.credentials:
        return bearer.credentials.strip()
    authorization = request.headers.get("Authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip()
    x_api_key = request.headers.get("X-Api-Key")
    if x_api_key:
        return x_api_key.strip()
    return None


def _reject() -> None:
    raise AUTH_ERROR


def _get_api_key_record(db: Session, presented_key_hash: str) -> ApiKey | None:
    return db.scalar(select(ApiKey).where(ApiKey.key_hash == presented_key_hash))


def _get_tenant(db: Session, tenant_id) -> Tenant | None:
    return db.get(Tenant, tenant_id)


def resolve_tenant_from_api_key(db: Session, raw_api_key: str) -> Tenant:
    presented_hash = hash_api_key(raw_api_key)
    record = _get_api_key_record(db, presented_hash)
    if record is None:
        _reject()

    # Defense-in-depth constant-time verification of stored hash match.
    if not hmac.compare_digest(record.key_hash, presented_hash):
        _reject()

    if record.revoked_at is not None:
        _reject()

    tenant = _get_tenant(db, record.tenant_id)
    if tenant is None:
        _reject()

    return tenant


def require_tenant(
    request: Request,
    db: Session = Depends(get_db),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> Tenant:
    raw_key = extract_api_key(request, bearer=bearer)
    if not raw_key:
        _reject()

    key_fingerprint = hash_api_key(raw_key)
    record = _get_api_key_record(db, key_fingerprint)
    if record is None:
        _reject()
    if not hmac.compare_digest(record.key_hash, key_fingerprint):
        _reject()
    if record.revoked_at is not None:
        _reject()

    tenant = _get_tenant(db, record.tenant_id)
    if tenant is None:
        _reject()
    if not tenant.can_write:
        increment_metric(
            METRIC_TENANT_WRITE_DENIED,
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            reason="tenant_inactive",
        )
        try:
            record_system_event(
                db,
                event_type="auth.tenant_write_denied",
                tenant_id=str(record.tenant_id),
                resource_type="tenant",
                resource_id=str(record.tenant_id),
                payload={
                    "reason": "tenant_inactive",
                    "request_id": getattr(getattr(request, "state", None), "request_id", None),
                },
                fail_open=True,
            )
            if hasattr(db, "commit"):
                db.commit()
        except Exception:
            if hasattr(db, "rollback"):
                db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    identity = f"apikey:{key_fingerprint}"
    try:
        if not RATE_LIMITER.allow(identity):
            increment_metric(
                METRIC_RATE_LIMIT_ENFORCED,
                request_id=getattr(getattr(request, "state", None), "request_id", None),
                reason="limit_exceeded",
            )
            log_structured(
                "security.rate_limit_enforced",
                reason="limit_exceeded",
                request_id=getattr(getattr(request, "state", None), "request_id", None),
            )
            try:
                record_system_event(
                    db,
                    event_type="auth.rate_limit.exceeded",
                    tenant_id=str(tenant.id),
                    resource_type="api_key",
                    payload={
                        "key_fingerprint_prefix": key_fingerprint[:12],
                        "request_id": getattr(getattr(request, "state", None), "request_id", None),
                    },
                    fail_open=True,
                )
                if hasattr(db, "commit"):
                    db.commit()
            except Exception:
                # Telemetry path must remain non-blocking.
                if hasattr(db, "rollback"):
                    db.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts",
            )
    except HTTPException:
        raise
    except Exception as exc:
        log_structured(
            "security.rate_limiter_unavailable",
            request_id=getattr(getattr(request, "state", None), "request_id", None),
        )
        try:
            record_system_event(
                db,
                event_type="auth.rate_limit.failure",
                tenant_id=str(tenant.id),
                resource_type="api_key",
                payload={
                    "failure_class": classify_failure(exc).value,
                    "request_id": getattr(getattr(request, "state", None), "request_id", None),
                },
                fail_open=True,
            )
            if hasattr(db, "commit"):
                db.commit()
        except Exception:
            if hasattr(db, "rollback"):
                db.rollback()
        if settings.env == "prod":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication unavailable",
            )

    request.state.tenant_id = tenant.id
    return tenant
