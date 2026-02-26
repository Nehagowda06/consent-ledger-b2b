import json
import logging
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import get_settings
from core.contracts import API_VERSION_HEADER, ErrorCode, error_body, resolve_api_version
from core.db import Base, SessionLocal, engine
from core.failure_modes import failure_policy, record_operation_failure
from core.logging_utils import configure_logging, log_request, monotonic_ms, request_id_from_request
from core.observability import best_effort_system_event
from core.release import release_artifact_dict, validate_release_startup
from core.system_events import record_system_event
from core.webhook_worker import start_webhook_worker, stop_webhook_worker
from models import consent, audit, tenant, api_key, idempotency_key, webhook, consent_lineage, system_event  # ensure models are imported so tables are registered
from routers.admin import router as admin_router
from routers.anchors import router as anchors_router
from routers.consents import router as consents_router
from routers.health import router as health_router
from routers.lineage_verify import router as lineage_verify_router
from routers.proofs import router as proofs_router
from routers.system_verify import router as system_verify_router
from routers.webhooks import router as webhooks_router

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Consent Ledger API",
    description=(
        "Tenant API uses `Authorization: Bearer <api_key>` and supports `Idempotency-Key` on write operations. "
        "Admin API uses `X-Admin-Api-Key` and is isolated from tenant authentication."
    ),
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "consents", "description": "Tenant-auth routes for consent lifecycle."},
        {"name": "webhooks", "description": "Tenant-auth webhook configuration and delivery tracking."},
        {"name": "admin", "description": "Admin-only tenant and API key controls."},
        {"name": "health", "description": "Operational liveness and diagnostics."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Api-Key", "X-Request-Id", API_VERSION_HEADER],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    try:
        api_version = resolve_api_version(request.headers.get(API_VERSION_HEADER))
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=error_body(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                request_id_from_request(request),
            ),
        )

    request_id = request_id_from_request(request)
    request.state.request_id = request_id
    request.state.api_version = api_version
    started = monotonic_ms()
    response = await call_next(request)
    skip_auto_envelope = (
        request.url.path == "/lineage/verify"
        or request.url.path == "/proofs/verify"
        or request.url.path == "/system/verify"
        or request.url.path == "/admin/system/export"
        or request.url.path.endswith("/lineage/export")
        or request.url.path.endswith("/proof")
    )
    if (
        not skip_auto_envelope
        and
        response.status_code < 400
        and response.headers.get("content-type", "").startswith("application/json")
    ):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            decoded = json.loads(body.decode("utf-8")) if body else None
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict) and ("data" in decoded or "error" in decoded):
            wrapped = decoded
        else:
            wrapped = {"data": decoded}
        response = JSONResponse(content=wrapped, status_code=response.status_code)
    response.headers["X-Request-Id"] = request_id
    response.headers[API_VERSION_HEADER] = api_version
    elapsed = monotonic_ms() - started
    log_request(request_id, request.method, request.url.path, response.status_code, elapsed)
    return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _map_http_error_code(status_code: int, detail: str) -> ErrorCode:
    lowered = (detail or "").lower()
    if status_code == 429:
        return ErrorCode.RATE_LIMIT_EXCEEDED
    if status_code == 409 and "idempotency" in lowered:
        return ErrorCode.IDEMPOTENCY_CONFLICT
    if status_code == 404:
        return ErrorCode.NOT_FOUND
    if status_code == 403 and "access denied" in lowered:
        return ErrorCode.TENANT_DISABLED
    if status_code == 403:
        return ErrorCode.FORBIDDEN
    if status_code == 401 and "missing" in lowered:
        return ErrorCode.AUTH_MISSING
    if status_code == 401:
        return ErrorCode.AUTH_INVALID
    return ErrorCode.INTERNAL_ERROR


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = "Request could not be processed"
    if exc.status_code in {401, 403, 404, 409, 422, 429}:
        message = str(exc.detail) if isinstance(exc.detail, str) else message
    code = _map_http_error_code(exc.status_code, str(exc.detail))
    best_effort_system_event(
        event_type="http.error",
        resource_type="request",
        resource_id=_request_id(request),
        payload={
            "path": request.url.path,
            "method": request.method,
            "status_code": exc.status_code,
            "error_code": str(code),
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message, _request_id(request)),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    best_effort_system_event(
        event_type="http.validation_error",
        resource_type="request",
        resource_id=_request_id(request),
        payload={
            "path": request.url.path,
            "method": request.method,
            "status_code": 422,
            "error_code": str(ErrorCode.VALIDATION_ERROR),
        },
    )
    return JSONResponse(
        status_code=422,
        content=error_body(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            _request_id(request),
        ),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    policy = failure_policy(exc)
    record_operation_failure(
        operation="http.request",
        exc=exc,
        resource_type="request",
        extra_payload={
            "path": request.url.path,
            "method": request.method,
            "request_id": _request_id(request),
            "error_code": str(ErrorCode.INTERNAL_ERROR),
        },
    )
    return JSONResponse(
        status_code=policy.http_status,
        content=error_body(
            ErrorCode.INTERNAL_ERROR,
            "Internal server error",
            _request_id(request),
        ),
    )


app.include_router(health_router)


@app.get("/")
def root():
    return {"status": "Consent Ledger API running"}


app.include_router(consents_router)
app.include_router(webhooks_router)
app.include_router(admin_router)
app.include_router(anchors_router)
app.include_router(lineage_verify_router)
app.include_router(proofs_router)
app.include_router(system_verify_router)


def _current_alembic_heads() -> str:
    ini_path = Path(__file__).resolve().parent / "alembic.ini"
    alembic_cfg = AlembicConfig(str(ini_path))
    script = ScriptDirectory.from_config(alembic_cfg)
    return ",".join(sorted(script.get_heads()))


@app.on_event("startup")
async def on_startup() -> None:
    if settings.env not in {"dev", "test", "staging", "prod"}:
        raise RuntimeError("ENV must be one of: dev, test, staging, prod")

    migration_heads = _current_alembic_heads()
    logger.info(
        "startup env=%s version_hash=%s migration_head=%s",
        settings.env,
        settings.version_hash,
        migration_heads,
    )

    if settings.env == "prod" and not settings.expected_alembic_head:
        logger.warning("EXPECTED_ALEMBIC_HEAD is not set; skipping migration-head enforcement")

    validate_release_startup(settings, migration_heads)
    if settings.env == "dev" and settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)

    connectivity_session = SessionLocal()
    try:
        if hasattr(connectivity_session, "execute"):
            connectivity_session.execute(text("SELECT 1"))
        else:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError("database connectivity check failed") from exc
    finally:
        connectivity_session.close()

    signing_mode = getattr(settings, "signing_mode", "required" if getattr(settings, "signing_required", False) else "optional")
    signing_enabled = bool(getattr(settings, "signing_enabled", False))
    if signing_mode == "disabled":
        logger.warning("identity_signing_disabled_explicit")
    elif not signing_enabled:
        logger.warning("identity_signing_unavailable_optional")

    startup_db = SessionLocal()
    try:
        record_system_event(
            startup_db,
            event_type="app.startup",
            resource_type="application",
            payload={
                "env": settings.env,
                "code_sha": settings.version_hash,
                "migration_head": migration_heads,
                "release": release_artifact_dict(settings),
            },
            fail_open=True,
        )
        startup_db.commit()
    except Exception:
        startup_db.rollback()
        logger.warning("startup_system_event_failed")
    finally:
        startup_db.close()
    start_webhook_worker(app)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_webhook_worker(app)
