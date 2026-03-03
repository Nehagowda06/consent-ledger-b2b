from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from core.config import get_settings
from core.db import engine

router = APIRouter(tags=["health"])
settings = get_settings()


def _current_alembic_heads() -> str:
    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    alembic_cfg = AlembicConfig(str(ini_path))
    script = ScriptDirectory.from_config(alembic_cfg)
    return ",".join(sorted(script.get_heads()))


@router.get("/health")
def health():
    # Backward-compatible liveness alias.
    return {"status": "ok"}


@router.get("/live")
def live():
    return {"status": "ok"}


@router.get("/ready")
def ready(request: Request):
    checks: dict[str, str] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "failed"

    expected_head = settings.expected_alembic_head.strip()
    if expected_head:
        try:
            current_head = _current_alembic_heads()
            checks["migration_head"] = "ok" if current_head == expected_head else "failed"
        except Exception:
            checks["migration_head"] = "failed"
    else:
        checks["migration_head"] = "skipped"

    if settings.signing_enabled:
        checks["signing_material"] = "ok"
    else:
        checks["signing_material"] = "failed" if settings.signing_required else "skipped"

    worker_enabled = bool(settings.webhook_worker_enabled)
    worker_task = getattr(getattr(request.app, "state", object()), "webhook_worker_task", None)
    if worker_enabled:
        checks["webhook_worker"] = "ok" if (worker_task is not None and not worker_task.done()) else "failed"
    else:
        checks["webhook_worker"] = "skipped"

    failed_checks = [name for name, result in checks.items() if result == "failed"]
    if failed_checks:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}


@router.get("/version")
def version():
    return {"name": settings.app_name, "version": settings.app_version}
