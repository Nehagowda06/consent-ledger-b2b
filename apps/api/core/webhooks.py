import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.failure_modes import classify_failure
from core.logging_utils import log_structured
from core.system_events import record_system_event
from models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookEndpoint

settings = get_settings()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def validate_webhook_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Invalid webhook URL")
    if settings.env == "prod" and parsed.scheme != "https":
        raise HTTPException(status_code=422, detail="Webhook URL must use https in prod")
    return url.strip()


def _hash_with_server_secret(raw: str) -> str:
    if not settings.webhook_signing_secret:
        raise HTTPException(status_code=500, detail="Webhook signing secret is not configured")
    return hmac.new(
        settings.webhook_signing_secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def derive_webhook_secret(endpoint_id: uuid.UUID) -> str:
    digest = hmac.new(
        settings.webhook_signing_secret.encode("utf-8"),
        f"endpoint:{endpoint_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    token = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return f"whsec_{token}"


def hash_webhook_secret(secret: str) -> str:
    return _hash_with_server_secret(f"webhook-secret:{secret}")


def mask_secret(secret: str) -> str:
    tail = secret[-4:] if len(secret) >= 4 else secret
    return f"****{tail}"


def canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_webhook_signature(secret: str, timestamp: int, body_text: str) -> str:
    signing_payload = f"{timestamp}.{body_text}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), signing_payload, hashlib.sha256).hexdigest()


def build_webhook_headers(timestamp: int, signature: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Webhook-Timestamp": str(timestamp),
        "X-Webhook-Signature": signature,
    }


def send_webhook_http(url: str, body_text: str, timestamp: int, signature: str, timeout: int = 10) -> int:
    body_bytes = body_text.encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=body_bytes,
        method="POST",
        headers=build_webhook_headers(timestamp, signature),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def enqueue_webhook_event(db: Session, tenant_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> None:
    endpoints = list(
        db.scalars(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id,
                WebhookEndpoint.enabled.is_(True),
            )
        ).all()
    )
    if not endpoints:
        return

    now = _now_utc()
    for endpoint in endpoints:
        db.add(
            WebhookDelivery(
                tenant_id=tenant_id,
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload_json=payload,
                status=WebhookDeliveryStatus.PENDING,
                attempt_count=0,
                next_attempt_at=now,
            )
        )


def _retry_delay_seconds(next_attempt_number: int) -> int:
    schedule = [60, 300, 900, 3600]
    index = min(max(next_attempt_number - 1, 0), len(schedule) - 1)
    return schedule[index]


def process_pending_deliveries(
    db: Session,
    tenant_id: uuid.UUID | None = None,
    now: datetime | None = None,
    max_batch: int = 100,
) -> int:
    now = now or _now_utc()
    stmt = select(WebhookDelivery).where(
        WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
        WebhookDelivery.next_attempt_at.is_not(None),
        WebhookDelivery.next_attempt_at <= now,
    )
    if tenant_id is not None:
        stmt = stmt.where(WebhookDelivery.tenant_id == tenant_id)
    deliveries = list(db.scalars(stmt.order_by(WebhookDelivery.created_at.asc()).limit(max_batch)).all())

    processed = 0
    for delivery in deliveries:
        endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
        if endpoint is None or not endpoint.enabled or endpoint.tenant_id != delivery.tenant_id:
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.last_error = "Webhook endpoint unavailable"
            delivery.last_attempt_at = now
            delivery.next_attempt_at = None
            delivery.attempt_count += 1
            log_structured(
                "webhook.delivery_failed",
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                tenant_id=str(delivery.tenant_id),
                reason="endpoint_unavailable",
            )
            record_system_event(
                db,
                event_type="webhook.delivery.attempt",
                tenant_id=str(delivery.tenant_id),
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                payload={"status": "failed", "reason": "endpoint_unavailable"},
                fail_open=True,
            )
            processed += 1
            continue

        secret_plain = derive_webhook_secret(endpoint.id)
        expected_hash = hash_webhook_secret(secret_plain)
        if not hmac.compare_digest(expected_hash, endpoint.secret_hash):
            delivery.status = WebhookDeliveryStatus.FAILED
            delivery.last_error = "Webhook endpoint secret mismatch"
            delivery.last_attempt_at = now
            delivery.next_attempt_at = None
            delivery.attempt_count += 1
            log_structured(
                "webhook.delivery_failed",
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                tenant_id=str(delivery.tenant_id),
                reason="secret_mismatch",
            )
            record_system_event(
                db,
                event_type="webhook.delivery.attempt",
                tenant_id=str(delivery.tenant_id),
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                payload={"status": "failed", "reason": "secret_mismatch"},
                fail_open=True,
            )
            processed += 1
            continue

        timestamp = int(time.time())
        body_text = canonical_json(delivery.payload_json)
        signature = compute_webhook_signature(secret_plain, timestamp, body_text)

        try:
            status_code = send_webhook_http(endpoint.url, body_text, timestamp, signature)
            success = 200 <= status_code < 300
            if success:
                delivery.status = WebhookDeliveryStatus.SENT
                delivery.last_error = None
                delivery.next_attempt_at = None
                record_system_event(
                    db,
                    event_type="webhook.delivery.attempt",
                    tenant_id=str(delivery.tenant_id),
                    resource_type="webhook_delivery",
                    resource_id=str(delivery.id),
                    payload={"status": "sent", "attempt": delivery.attempt_count + 1},
                    fail_open=True,
                )
            else:
                next_attempt_number = delivery.attempt_count + 1
                if next_attempt_number >= settings.webhook_max_attempts:
                    delivery.status = WebhookDeliveryStatus.FAILED
                    delivery.next_attempt_at = None
                else:
                    delivery.status = WebhookDeliveryStatus.PENDING
                    delay = _retry_delay_seconds(next_attempt_number)
                    delivery.next_attempt_at = now + timedelta(seconds=delay)
                delivery.last_error = f"HTTP {status_code}"
                log_structured(
                    "webhook.delivery_failed",
                    resource_type="webhook_delivery",
                    resource_id=str(delivery.id),
                    tenant_id=str(delivery.tenant_id),
                    reason=f"http_{status_code}",
                )
                record_system_event(
                    db,
                    event_type="webhook.delivery.attempt",
                    tenant_id=str(delivery.tenant_id),
                    resource_type="webhook_delivery",
                    resource_id=str(delivery.id),
                    payload={"status": "failed", "http_status": status_code, "attempt": next_attempt_number},
                    fail_open=True,
                )
            delivery.attempt_count += 1
            delivery.last_attempt_at = now
        except Exception as exc:  # pragma: no cover - network failures are mocked in tests
            next_attempt_number = delivery.attempt_count + 1
            if next_attempt_number >= settings.webhook_max_attempts:
                delivery.status = WebhookDeliveryStatus.FAILED
                delivery.next_attempt_at = None
            else:
                delivery.status = WebhookDeliveryStatus.PENDING
                delay = _retry_delay_seconds(next_attempt_number)
                delivery.next_attempt_at = now + timedelta(seconds=delay)
            delivery.last_error = str(exc)[:500]
            log_structured(
                "webhook.delivery_failed",
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                tenant_id=str(delivery.tenant_id),
                reason="network_error",
            )
            record_system_event(
                db,
                event_type="webhook.delivery.attempt",
                tenant_id=str(delivery.tenant_id),
                resource_type="webhook_delivery",
                resource_id=str(delivery.id),
                payload={
                    "status": "failed",
                    "reason": "network_error",
                    "attempt": next_attempt_number,
                    "failure_class": classify_failure(exc).value,
                },
                fail_open=True,
            )
            delivery.attempt_count += 1
            delivery.last_attempt_at = now
        processed += 1

    if processed:
        db.commit()
    return processed
