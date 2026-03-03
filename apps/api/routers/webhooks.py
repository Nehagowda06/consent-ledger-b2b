import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.auth import require_tenant
from core.contracts import paginated
from core.deps import get_db
from core.webhooks import (
    derive_webhook_secret,
    enqueue_webhook_event,
    hash_webhook_secret,
    mask_secret,
    process_pending_deliveries,
    validate_webhook_url,
)
from models.tenant import Tenant
from models.webhook import WebhookDelivery, WebhookEndpoint
from schemas.webhook import DeliveryOut, WebhookCreate, WebhookCreateOut, WebhookOut, WebhookPatch

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _endpoint_out(endpoint: WebhookEndpoint, secret: str | None = None) -> WebhookOut | WebhookCreateOut:
    derived = secret or derive_webhook_secret(endpoint.id)
    base = {
        "id": endpoint.id,
        "url": endpoint.url,
        "label": endpoint.label,
        "enabled": endpoint.enabled,
        "secret_masked": mask_secret(derived),
        "created_at": endpoint.created_at,
        "updated_at": endpoint.updated_at,
    }
    if secret is not None:
        return WebhookCreateOut(**base, secret=secret)
    return WebhookOut(**base)


@router.post(
    "",
    response_model=WebhookCreateOut,
    description="Tenant-auth route. Creates a webhook endpoint and returns secret once.",
)
def create_webhook(
    payload: WebhookCreate,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    endpoint_id = uuid.uuid4()
    secret = derive_webhook_secret(endpoint_id)
    endpoint = WebhookEndpoint(
        id=endpoint_id,
        tenant_id=tenant.id,
        url=validate_webhook_url(str(payload.url)),
        label=payload.label,
        enabled=payload.enabled,
        secret_hash=hash_webhook_secret(secret),
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return _endpoint_out(endpoint, secret=secret)


@router.get(
    "",
    response_model=dict,
    description="Tenant-auth route. Supports pagination with limit/offset.",
)
def list_webhooks(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    limit = limit if isinstance(limit, int) else int(getattr(limit, "default", 50))
    offset = offset if isinstance(offset, int) else int(getattr(offset, "default", 0))
    total = int(
        db.scalar(
            select(func.count()).select_from(WebhookEndpoint).where(WebhookEndpoint.tenant_id == tenant.id)
        )
        or 0
    )
    endpoints = list(
        db.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.tenant_id == tenant.id)
            .order_by(WebhookEndpoint.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    data = [_endpoint_out(endpoint) for endpoint in endpoints]
    return paginated(data, limit=limit, offset=offset, count=total)


@router.patch("/{endpoint_id}", response_model=WebhookOut)
def update_webhook(
    endpoint_id: uuid.UUID,
    payload: WebhookPatch,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    if payload.url is not None:
        endpoint.url = validate_webhook_url(str(payload.url))
    if payload.label is not None:
        endpoint.label = payload.label
    if payload.enabled is not None:
        endpoint.enabled = payload.enabled
    endpoint.updated_at = datetime.now(timezone.utc)
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return _endpoint_out(endpoint)


@router.post(
    "/{endpoint_id}/test",
    description="Tenant-auth route. Enqueues a signed test webhook delivery.",
)
def enqueue_test_event(
    endpoint_id: uuid.UUID,
    process_now: bool = False,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    endpoint = db.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.tenant_id == tenant.id,
        )
    )
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    enqueue_webhook_event(
        db,
        tenant_id=tenant.id,
        event_type="webhook.test",
        payload={
            "type": "webhook.test",
            "tenant_id": str(tenant.id),
            "endpoint_id": str(endpoint.id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    db.commit()

    processed = 0
    if process_now:
        processed = process_pending_deliveries(db, tenant_id=tenant.id)
    return {"queued": True, "processed": processed}


@router.get(
    "/deliveries",
    response_model=dict,
    description=(
        "Tenant-auth route. Lists webhook deliveries. "
        "Delivery attempts include HMAC signature headers "
        "`X-Webhook-Timestamp` and `X-Webhook-Signature`."
    ),
)
def list_deliveries(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    limit = limit if isinstance(limit, int) else int(getattr(limit, "default", 50))
    offset = offset if isinstance(offset, int) else int(getattr(offset, "default", 0))
    total = int(
        db.scalar(
            select(func.count()).select_from(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant.id)
        )
        or 0
    )
    deliveries = list(
        db.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.tenant_id == tenant.id)
            .order_by(WebhookDelivery.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    data = [
        DeliveryOut(
            id=delivery.id,
            endpoint_id=delivery.endpoint_id,
            event_type=delivery.event_type,
            status=delivery.status.value if hasattr(delivery.status, "value") else str(delivery.status),
            attempt_count=delivery.attempt_count,
            last_attempt_at=delivery.last_attempt_at,
            next_attempt_at=delivery.next_attempt_at,
            last_error=delivery.last_error,
            created_at=delivery.created_at,
        )
        for delivery in deliveries
    ]
    return paginated(data, limit=limit, offset=offset, count=total)


@router.post("/deliveries/process-now")
def process_now(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(require_tenant),
):
    processed = process_pending_deliveries(db, tenant_id=tenant.id)
    return {"processed": processed}
