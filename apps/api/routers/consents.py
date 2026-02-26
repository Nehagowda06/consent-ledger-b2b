from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from uuid import UUID
from datetime import datetime, timezone

try:
    # Pydantic v2
    from pydantic import BaseModel, ConfigDict
    _PYDANTIC_V2 = True
except ImportError:
    # Pydantic v1
    from pydantic import BaseModel
    ConfigDict = None
    _PYDANTIC_V2 = False

from core.deps import get_db
from core.auth import require_tenant
from core.contracts import paginated
from core.idempotency import (
    build_request_hash,
    check_idempotency,
    get_idempotency_key,
    store_idempotency_result,
)
from core.failure_modes import record_operation_failure
from core.observability import (
    METRIC_TENANT_WRITE_DENIED,
    best_effort_system_event,
    increment_metric,
)
from core.consent_proof import build_consent_proof
from core.lineage import add_lineage_event, verify_lineage_chain
from core.lineage_export import export_consent_lineage
from core.webhooks import enqueue_webhook_event
from models.tenant import Tenant
from models.consent import Consent, ConsentStatus
from models.audit import AuditEvent
from models.consent_lineage import ConsentLineageEvent
from schemas.consent import ConsentCreate, ConsentOut, ConsentUpsert

router = APIRouter(prefix="/consents", tags=["consents"])


def _ensure_tenant_writable(tenant: Tenant) -> None:
    can_write = getattr(tenant, "can_write", None)
    if can_write is None:
        is_active = bool(getattr(tenant, "is_active", True))
        lifecycle = getattr(tenant, "lifecycle_state", None)
        lifecycle_value = getattr(lifecycle, "value", lifecycle)
        can_write = is_active and lifecycle_value in (None, "active")
    if not bool(can_write):
        increment_metric(METRIC_TENANT_WRITE_DENIED, reason="tenant_write_forbidden")
        best_effort_system_event(
            event_type="consent.tenant_write_denied",
            tenant_id=str(tenant.id),
            resource_type="tenant",
            resource_id=str(tenant.id),
            payload={"reason": "tenant_write_forbidden"},
        )
        raise HTTPException(status_code=403, detail="Access denied")


class AuditEventOut(BaseModel):
    consent_id: UUID
    action: str
    actor: str
    at: datetime

    if _PYDANTIC_V2:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            orm_mode = True


class LineageEventOut(BaseModel):
    action: str
    event_hash: str
    prev_event_hash: str | None
    created_at: datetime


class ConsentLineageOut(BaseModel):
    consent_id: UUID
    verified: bool
    events: list[LineageEventOut]


class ConsentProofRequest(BaseModel):
    asserted_at: datetime


@router.post(
    "",
    response_model=ConsentOut,
    description=(
        "Tenant-auth route. Supports `Idempotency-Key` for safe retries. "
        "Subject to per-key rate limits."
    ),
)
def create_consent(
    payload: ConsentCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
    request: Request = None,
    response: Response = None,
):
    _ensure_tenant_writable(tenant)
    idempotency_key = get_idempotency_key(request)
    request_hash = None
    if idempotency_key:
        body = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload.dict()
        request_hash = build_request_hash(request.method, request.url.path, body)
        replay = check_idempotency(db, tenant.id, idempotency_key, request_hash)
        if replay:
            if response is not None:
                response.status_code = replay.status_code
            return replay.response_json

    try:
        consent = Consent(
            tenant_id=tenant.id,
            subject_id=payload.subject_id,
            purpose=payload.purpose,
        )
        db.add(consent)
        db.flush()

        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=consent.id,
                action="CREATED",
                actor="system",
            )
        )
        add_lineage_event(db, consent, "created")
        enqueue_webhook_event(
            db,
            tenant_id=tenant.id,
            event_type="consent.created",
            payload={
                "type": "consent.created",
                "consent_id": str(consent.id),
                "subject_id": consent.subject_id,
                "purpose": consent.purpose,
                "status": consent.status.value if hasattr(consent.status, "value") else str(consent.status),
            },
        )

        db.flush()
        db.refresh(consent)
        response_payload = jsonable_encoder(consent)
        store_idempotency_result(
            db,
            tenant_id=tenant.id,
            key=idempotency_key,
            request_hash=request_hash,
            response_json=response_payload,
            status_code=200,
        )
        db.commit()
        if response is not None:
            response.status_code = 200
        return response_payload if idempotency_key else consent
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="consent.create",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="consent",
            extra_payload={"path": "/consents"},
        )
        raise


@router.put(
    "",
    response_model=ConsentOut,
    description=(
        "Tenant-auth route. Upsert consent by (subject_id, purpose). "
        "Supports `Idempotency-Key` for safe retries and is rate limited."
    ),
)
def upsert_consent(
    payload: ConsentUpsert,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
    request: Request = None,
    response: Response = None,
):
    _ensure_tenant_writable(tenant)
    idempotency_key = get_idempotency_key(request)
    request_hash = None
    if idempotency_key:
        body = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload.dict()
        request_hash = build_request_hash(request.method, request.url.path, body)
        replay = check_idempotency(db, tenant.id, idempotency_key, request_hash)
        if replay:
            if response is not None:
                response.status_code = replay.status_code
            return replay.response_json

    now = datetime.now(timezone.utc)
    try:
        consent = db.scalar(
            select(Consent).where(
                Consent.tenant_id == tenant.id,
                Consent.subject_id == payload.subject_id,
                Consent.purpose == payload.purpose,
            )
        )

        if not consent:
            consent = Consent(
                tenant_id=tenant.id,
                subject_id=payload.subject_id,
                purpose=payload.purpose,
                status=payload.status,
                revoked_at=now if payload.status == ConsentStatus.REVOKED else None,
            )
            db.add(consent)
            db.flush()

            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    consent_id=consent.id,
                    action="consent.created",
                    actor="system",
                )
            )
            webhook_event_type = "consent.created"
            lineage_action = "created"
        else:
            if consent.status != payload.status:
                consent.status = payload.status
                consent.updated_at = now
                consent.revoked_at = now if payload.status == ConsentStatus.REVOKED else None
                action = "consent.updated"
                webhook_event_type = "consent.updated"
                lineage_action = "updated"
            else:
                action = "consent.noop"
                webhook_event_type = "consent.noop"
                lineage_action = "noop"

            db.add(consent)
            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    consent_id=consent.id,
                    action=action,
                    actor="system",
                )
            )
        add_lineage_event(db, consent, lineage_action)
        enqueue_webhook_event(
            db,
            tenant_id=tenant.id,
            event_type=webhook_event_type,
            payload={
                "type": webhook_event_type,
                "consent_id": str(consent.id),
                "subject_id": consent.subject_id,
                "purpose": consent.purpose,
                "status": consent.status.value if hasattr(consent.status, "value") else str(consent.status),
            },
        )

        db.flush()
        db.refresh(consent)
        response_payload = jsonable_encoder(consent)
        store_idempotency_result(
            db,
            tenant_id=tenant.id,
            key=idempotency_key,
            request_hash=request_hash,
            response_json=response_payload,
            status_code=200,
        )
        db.commit()
        if response is not None:
            response.status_code = 200
        return response_payload if idempotency_key else consent
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="consent.upsert",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="consent",
            extra_payload={"path": "/consents"},
        )
        raise


@router.get("/{consent_id}", response_model=ConsentOut)
def get_consent(
    consent_id: UUID,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    consent = db.scalar(
        select(Consent).where(
            Consent.id == consent_id,
            Consent.tenant_id == tenant.id,
        )
    )
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    return consent


@router.get("", response_model=dict, description="Tenant-auth route. Supports pagination with limit/offset.")
def list_consents(
    subject_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    limit = limit if isinstance(limit, int) else int(getattr(limit, "default", 50))
    offset = offset if isinstance(offset, int) else int(getattr(offset, "default", 0))
    stmt = select(Consent).where(Consent.tenant_id == tenant.id)
    count_stmt = select(func.count()).select_from(Consent).where(Consent.tenant_id == tenant.id)
    if subject_id:
        stmt = stmt.where(Consent.subject_id == subject_id)
        count_stmt = count_stmt.where(Consent.subject_id == subject_id)
    total = int(db.scalar(count_stmt) or 0)
    items = list(db.scalars(stmt.order_by(Consent.created_at.desc()).offset(offset).limit(limit)).all())
    return paginated(items, limit=limit, offset=offset, count=total)


@router.post(
    "/{consent_id}/revoke",
    response_model=ConsentOut,
    description="Tenant-auth route. Supports `Idempotency-Key` for safe retries.",
)
def revoke_consent(
    consent_id: UUID,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
    request: Request = None,
    response: Response = None,
):
    _ensure_tenant_writable(tenant)
    idempotency_key = get_idempotency_key(request)
    request_hash = None
    if idempotency_key:
        request_hash = build_request_hash(request.method, request.url.path, {})
        replay = check_idempotency(db, tenant.id, idempotency_key, request_hash)
        if replay:
            if response is not None:
                response.status_code = replay.status_code
            return replay.response_json

    try:
        consent = db.scalar(
            select(Consent).where(
                Consent.id == consent_id,
                Consent.tenant_id == tenant.id,
            )
        )
        if not consent:
            raise HTTPException(status_code=404, detail="Consent not found")

        if consent.status == ConsentStatus.REVOKED:
            raise HTTPException(status_code=409, detail="Consent already revoked")

        consent.status = ConsentStatus.REVOKED
        consent.revoked_at = datetime.now(timezone.utc)
        db.add(consent)

        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                consent_id=consent.id,
                action="REVOKED",
                actor="system",
            )
        )
        add_lineage_event(db, consent, "revoked")
        enqueue_webhook_event(
            db,
            tenant_id=tenant.id,
            event_type="consent.revoked",
            payload={
                "type": "consent.revoked",
                "consent_id": str(consent.id),
                "subject_id": consent.subject_id,
                "purpose": consent.purpose,
                "status": consent.status.value if hasattr(consent.status, "value") else str(consent.status),
            },
        )

        db.flush()
        db.refresh(consent)
        response_payload = jsonable_encoder(consent)
        store_idempotency_result(
            db,
            tenant_id=tenant.id,
            key=idempotency_key,
            request_hash=request_hash,
            response_json=response_payload,
            status_code=200,
        )
        db.commit()
        if response is not None:
            response.status_code = 200
        return response_payload if idempotency_key else consent
    except Exception as exc:
        db.rollback()
        record_operation_failure(
            operation="consent.revoke",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="consent",
            resource_id=str(consent_id),
            extra_payload={"path": f"/consents/{consent_id}/revoke"},
        )
        raise


@router.get(
    "/{consent_id}/audit",
    response_model=dict,
    description="Tenant-auth route. Lists audit events for a consent with pagination.",
)
def get_consent_audit(
    consent_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    limit = limit if isinstance(limit, int) else int(getattr(limit, "default", 50))
    offset = offset if isinstance(offset, int) else int(getattr(offset, "default", 0))
    consent = db.scalar(
        select(Consent).where(
            Consent.id == consent_id,
            Consent.tenant_id == tenant.id,
        )
    )
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    base_filter = (
        (AuditEvent.consent_id == consent_id) & (AuditEvent.tenant_id == tenant.id)
    )
    total = int(db.scalar(select(func.count()).select_from(AuditEvent).where(base_filter)) or 0)
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(base_filter)
            .order_by(AuditEvent.at.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return paginated(events, limit=limit, offset=offset, count=total)


@router.get(
    "/{consent_id}/lineage",
    response_model=dict,
    description="Tenant-auth route. Returns tamper-evident lineage verification for a consent.",
)
def get_consent_lineage(
    consent_id: UUID,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    consent = db.scalar(
        select(Consent).where(
            Consent.id == consent_id,
            Consent.tenant_id == tenant.id,
        )
    )
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    events = list(
        db.scalars(
            select(ConsentLineageEvent)
            .where(
                ConsentLineageEvent.tenant_id == tenant.id,
                ConsentLineageEvent.consent_id == consent_id,
            )
            .order_by(ConsentLineageEvent.created_at.asc(), ConsentLineageEvent.id.asc())
        ).all()
    )
    verified = verify_lineage_chain(events, consent)
    payload = ConsentLineageOut(
        consent_id=consent.id,
        verified=verified,
        events=[
            LineageEventOut(
                action=event.action,
                event_hash=event.event_hash,
                prev_event_hash=event.prev_event_hash,
                created_at=event.created_at,
            )
            for event in events
        ],
    )
    return payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload.dict()


@router.get(
    "/{consent_id}/lineage/export",
    response_model=dict,
    description="Tenant-auth route. Exports portable lineage proof artifact.",
)
def get_consent_lineage_export(
    consent_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    consent = db.scalar(
        select(Consent).where(
            Consent.id == consent_id,
            Consent.tenant_id == tenant.id,
        )
    )
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    response.headers["Cache-Control"] = "no-store"
    return export_consent_lineage(consent_id=consent_id, tenant_id=tenant.id, db=db)


@router.post(
    "/{consent_id}/proof",
    response_model=dict,
    description="Tenant-auth route. Builds portable consent state proof at asserted time.",
)
def create_consent_proof(
    consent_id: UUID,
    payload: ConsentProofRequest,
    response: Response,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    consent = db.scalar(
        select(Consent).where(
            Consent.id == consent_id,
            Consent.tenant_id == tenant.id,
        )
    )
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    try:
        proof = build_consent_proof(
            consent_id=consent_id,
            tenant_id=tenant.id,
            asserted_at=payload.asserted_at,
            db=db,
        )
    except ValueError as exc:
        record_operation_failure(
            operation="consent.proof.create",
            exc=exc,
            db=db,
            tenant_id=tenant.id,
            resource_type="consent",
            resource_id=str(consent_id),
            extra_payload={"path": f"/consents/{consent_id}/proof"},
        )
        raise HTTPException(status_code=422, detail=str(exc))

    response.headers["Cache-Control"] = "no-store"
    return proof
