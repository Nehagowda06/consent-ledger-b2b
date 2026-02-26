import uuid
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.admin_auth import require_admin
from core.api_keys import generate_api_key, hash_api_key
from core.config import get_settings
from core.contracts import paginated
from core.deps import get_db
from core.failure_modes import record_operation_failure
from core.external_anchor import append_anchor_commit, export_anchor_snapshot
from core.system_forensics import export_system_ledger, verify_system_ledger
from core.system_events import record_system_event
from models.api_key import ApiKey
from models.audit import AuditEvent
from models.tenant import Tenant, TenantLifecycleState
from schemas.admin import ApiKeyCreateIn, ApiKeyCreateOut, TenantCreateIn, TenantOut

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
ZERO_CONSENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/tenants", response_model=TenantOut, description="Admin-only route.")
def create_tenant(payload: TenantCreateIn, db: Session = Depends(get_db)):
    try:
        tenant = Tenant(name=payload.name.strip())
        db.add(tenant)
        db.flush()

        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=ZERO_CONSENT_ID,
                action="tenant.created",
                actor="admin",
            )
        )
        record_system_event(
            db,
            event_type="admin.tenant.create",
            tenant_id=str(tenant.id),
            resource_type="tenant",
            resource_id=str(tenant.id),
            payload={"name": tenant.name},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.tenant.create",
            exc=exc,
            db=db,
            resource_type="tenant",
            extra_payload={"path": "/admin/tenants"},
        )
        raise HTTPException(status_code=409, detail="Tenant already exists")
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.tenant.create",
            exc=exc,
            db=db,
            resource_type="tenant",
            extra_payload={"path": "/admin/tenants"},
        )
        raise
    db.refresh(tenant)
    return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)


@router.get("/tenants", response_model=dict, description="Admin-only route. Supports pagination.")
def list_tenants(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    limit = limit if isinstance(limit, int) else int(getattr(limit, "default", 50))
    offset = offset if isinstance(offset, int) else int(getattr(offset, "default", 0))
    total = int(db.scalar(select(func.count()).select_from(Tenant)) or 0)
    tenants = list(
        db.scalars(select(Tenant).order_by(Tenant.created_at.desc()).offset(offset).limit(limit)).all()
    )
    data = [
        TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)
        for tenant in tenants
    ]
    return paginated(data, limit=limit, offset=offset, count=total)


@router.patch("/tenants/{tenant_id}/suspend", response_model=TenantOut, description="Admin-only route.")
def suspend_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant.lifecycle_state == TenantLifecycleState.SUSPENDED:
        return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)

    try:
        tenant.lifecycle_state = TenantLifecycleState.SUSPENDED
        tenant.is_active = False
        db.add(tenant)
        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=ZERO_CONSENT_ID,
                action="tenant.suspended",
                actor="admin",
            )
        )
        record_system_event(
            db,
            event_type="tenant.suspended",
            tenant_id=str(tenant.id),
            resource_type="tenant",
            resource_id=str(tenant.id),
            payload={"lifecycle_state": TenantLifecycleState.SUSPENDED.value},
        )
        db.commit()
        db.refresh(tenant)
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.tenant.suspend",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="tenant",
            resource_id=str(tenant.id),
            extra_payload={"path": f"/admin/tenants/{tenant.id}/suspend"},
        )
        raise
    return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)


@router.patch("/tenants/{tenant_id}/reactivate", response_model=TenantOut, description="Admin-only route.")
def reactivate_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.lifecycle_state == TenantLifecycleState.DISABLED:
        raise HTTPException(status_code=409, detail="Disabled tenant cannot be reactivated")
    if tenant.lifecycle_state == TenantLifecycleState.ACTIVE and tenant.is_active:
        return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)

    try:
        tenant.lifecycle_state = TenantLifecycleState.ACTIVE
        tenant.is_active = True
        db.add(tenant)
        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=ZERO_CONSENT_ID,
                action="tenant.reactivated",
                actor="admin",
            )
        )
        record_system_event(
            db,
            event_type="tenant.reactivated",
            tenant_id=str(tenant.id),
            resource_type="tenant",
            resource_id=str(tenant.id),
            payload={"lifecycle_state": TenantLifecycleState.ACTIVE.value},
        )
        db.commit()
        db.refresh(tenant)
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.tenant.reactivate",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="tenant",
            resource_id=str(tenant.id),
            extra_payload={"path": f"/admin/tenants/{tenant.id}/reactivate"},
        )
        raise
    return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)


@router.patch("/tenants/{tenant_id}/disable", response_model=TenantOut, description="Admin-only route.")
def disable_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if tenant.lifecycle_state != TenantLifecycleState.DISABLED:
        try:
            tenant.lifecycle_state = TenantLifecycleState.DISABLED
            tenant.is_active = False
            db.add(tenant)
            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    consent_id=ZERO_CONSENT_ID,
                    action="tenant.disabled",
                    actor="admin",
                )
            )
            record_system_event(
                db,
                event_type="tenant.disabled",
                tenant_id=str(tenant.id),
                resource_type="tenant",
                resource_id=str(tenant.id),
                payload={"is_active": False, "lifecycle_state": TenantLifecycleState.DISABLED.value},
            )
            record_system_event(
                db,
                event_type="admin.tenant.disable",
                tenant_id=str(tenant.id),
                resource_type="tenant",
                resource_id=str(tenant.id),
                payload={"is_active": False, "lifecycle_state": TenantLifecycleState.DISABLED.value},
            )
            db.commit()
            db.refresh(tenant)
        except Exception as exc:
            db.rollback()
            record_operation_failure(
                operation="admin.tenant.disable",
                exc=exc,
                db=db,
                tenant_id=tenant.id,
                resource_type="tenant",
                resource_id=str(tenant.id),
                extra_payload={"path": f"/admin/tenants/{tenant.id}/disable"},
            )
            raise

    return TenantOut(id=tenant.id, name=tenant.name, is_active=tenant.is_active, created_at=tenant.created_at)


@router.post("/tenants/{tenant_id}/api-keys", response_model=ApiKeyCreateOut, description="Admin-only route.")
def create_api_key(tenant_id: uuid.UUID, payload: ApiKeyCreateIn, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    plaintext_key = generate_api_key()
    try:
        api_key = ApiKey(
            tenant_id=tenant.id,
            key_hash=hash_api_key(plaintext_key),
            label=payload.label,
        )
        db.add(api_key)
        db.flush()

        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=ZERO_CONSENT_ID,
                action="api_key.created",
                actor="admin",
            )
        )
        record_system_event(
            db,
            event_type="admin.api_key.create",
            tenant_id=str(tenant.id),
            resource_type="api_key",
            resource_id=str(api_key.id),
            payload={"label": api_key.label},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.api_key.create",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="api_key",
            extra_payload={"path": f"/admin/tenants/{tenant.id}/api-keys"},
        )
        raise
    db.refresh(api_key)
    return ApiKeyCreateOut(
        id=api_key.id,
        tenant_id=api_key.tenant_id,
        label=api_key.label,
        created_at=api_key.created_at,
        api_key=plaintext_key,
    )


@router.post("/api-keys/{api_key_id}/revoke", description="Admin-only route.")
def revoke_api_key(api_key_id: uuid.UUID, db: Session = Depends(get_db)):
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")

    if api_key.revoked_at is None:
        try:
            api_key.revoked_at = datetime.now(timezone.utc)
            db.add(api_key)
            db.add(
                AuditEvent(
                    tenant_id=api_key.tenant_id,
                    consent_id=ZERO_CONSENT_ID,
                    action="api_key.revoked",
                    actor="admin",
                )
            )
            record_system_event(
                db,
                event_type="admin.api_key.revoke",
                tenant_id=str(api_key.tenant_id),
                resource_type="api_key",
                resource_id=str(api_key.id),
                payload={"revoked": True},
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            record_operation_failure(
                operation="admin.api_key.revoke",
                exc=exc,
                db=db,
                tenant_id=api_key.tenant_id,
                resource_type="api_key",
                resource_id=str(api_key.id),
                extra_payload={"path": f"/admin/api-keys/{api_key.id}/revoke"},
            )
            raise

    return {"revoked": True}


@router.post("/anchors/snapshot", response_model=dict, description="Admin-only route.")
def create_anchor_snapshot(response: Response, db: Session = Depends(get_db)):
    snapshot = export_anchor_snapshot(db)
    try:
        record_system_event(
            db,
            event_type="admin.external_anchor.snapshot",
            resource_type="external_anchor",
            payload={"anchor_count": snapshot.get("anchor_count", 0), "digest": snapshot.get("digest")},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="admin.external_anchor.snapshot",
            exc=exc,
            db=db,
            resource_type="external_anchor",
            extra_payload={"path": "/admin/anchors/snapshot"},
        )
        raise
    response.headers["Cache-Control"] = "no-store"

    commit_path = settings.external_anchor_commit_path
    if commit_path:
        try:
            append_anchor_commit(commit_path, snapshot)
        except OSError as exc:
            # Non-fatal: snapshot creation must still succeed when optional publish hook fails.
            logger.warning("external_anchor_commit_failed path=%s error=%s", commit_path, exc.__class__.__name__)

    return snapshot


@router.get("/system/export", response_model=dict, description="Admin-only route.")
def export_system_events(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return export_system_ledger(db)


@router.get("/system/verify", response_model=dict, description="Admin-only route.")
def verify_system_events(db: Session = Depends(get_db)):
    exported = export_system_ledger(db)
    result = verify_system_ledger(exported["events"])
    return {
        "verified": bool(result.get("verified")),
        "event_count": len(exported["events"]),
        "failure_index": result.get("failure_index"),
        "failure_reason": result.get("failure_reason"),
    }
