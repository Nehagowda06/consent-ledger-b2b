import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import get_settings
from core.db import Base
from core.webhooks import (
    build_webhook_headers,
    canonical_json,
    compute_webhook_signature,
    process_pending_deliveries,
)
from models.consent import ConsentStatus
from models.tenant import Tenant
from models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookEndpoint
from routers.consents import revoke_consent, upsert_consent
from routers.webhooks import create_webhook, list_deliveries, list_webhooks, update_webhook
from schemas.consent import ConsentUpsert
from schemas.webhook import WebhookCreate, WebhookPatch


class WebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-a-webhooks")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-b-webhooks")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_webhook_returns_secret_once_get_hides(self) -> None:
        created = create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="primary", enabled=True),
            db=self.db,
            tenant=self.tenant_a,
        )
        self.assertTrue(created.secret.startswith("whsec_"))
        self.assertTrue(created.secret_masked.startswith("****"))

        listed = list_webhooks(db=self.db, tenant=self.tenant_a)
        self.assertEqual(len(listed["data"]), 1)
        self.assertFalse(hasattr(listed["data"][0], "secret"))
        self.assertEqual(listed["data"][0].label, "primary")

    def test_enqueue_happens_on_upsert_and_revoke(self) -> None:
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="queue", enabled=True),
            db=self.db,
            tenant=self.tenant_a,
        )
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="subject-1", purpose="analytics", status=ConsentStatus.ACTIVE),
            db=self.db,
            tenant=self.tenant_a,
        )
        revoke_consent(consent_id=consent.id, db=self.db, tenant=self.tenant_a)

        deliveries = list(
            self.db.scalars(
                select(WebhookDelivery).where(WebhookDelivery.tenant_id == self.tenant_a.id)
            ).all()
        )
        self.assertEqual(len(deliveries), 2)
        event_types = {d.event_type for d in deliveries}
        self.assertIn("consent.created", event_types)
        self.assertIn("consent.revoked", event_types)

    def test_signing_headers_deterministic(self) -> None:
        timestamp = 1_700_000_000
        secret = "whsec_test_secret"
        payload = {"a": 2, "b": 1}
        body = canonical_json(payload)
        signature = compute_webhook_signature(secret, timestamp, body)
        headers = build_webhook_headers(timestamp, signature)

        expected = compute_webhook_signature(secret, timestamp, '{"a":2,"b":1}')
        self.assertEqual(signature, expected)
        self.assertEqual(headers["X-Webhook-Timestamp"], str(timestamp))
        self.assertEqual(headers["X-Webhook-Signature"], signature)
        self.assertEqual(headers["Content-Type"], "application/json")

    @patch("core.webhooks.send_webhook_http", return_value=500)
    @patch("core.webhooks.time.time", return_value=1_700_000_000)
    def test_retry_scheduling(self, _mock_time, _mock_send) -> None:
        endpoint = create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="retry", enabled=True),
            db=self.db,
            tenant=self.tenant_a,
        )
        endpoint_model = self.db.scalar(
            select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint.id)
        )
        now = datetime(2026, 2, 23, tzinfo=timezone.utc)
        delivery = WebhookDelivery(
            tenant_id=self.tenant_a.id,
            endpoint_id=endpoint_model.id,
            event_type="consent.created",
            payload_json={"x": 1},
            status=WebhookDeliveryStatus.PENDING,
            attempt_count=0,
            next_attempt_at=now,
        )
        self.db.add(delivery)
        self.db.commit()

        process_pending_deliveries(self.db, tenant_id=self.tenant_a.id, now=now)
        self.db.refresh(delivery)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.status, WebhookDeliveryStatus.PENDING)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertIsNotNone(delivery.last_attempt_at)
        self.assertGreater(delivery.next_attempt_at, delivery.last_attempt_at)

        delivery.attempt_count = get_settings().webhook_max_attempts - 1
        delivery.next_attempt_at = now
        delivery.status = WebhookDeliveryStatus.PENDING
        self.db.add(delivery)
        self.db.commit()

        process_pending_deliveries(self.db, tenant_id=self.tenant_a.id, now=now + timedelta(minutes=2))
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, WebhookDeliveryStatus.FAILED)
        self.assertIsNone(delivery.next_attempt_at)

    def test_tenant_isolation_for_webhooks_and_deliveries(self) -> None:
        created = create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/a", label="tenant-a", enabled=True),
            db=self.db,
            tenant=self.tenant_a,
        )
        self.db.add(
            WebhookDelivery(
                tenant_id=self.tenant_a.id,
                endpoint_id=created.id,
                event_type="consent.created",
                payload_json={"ok": True},
                status=WebhookDeliveryStatus.PENDING,
                attempt_count=0,
                next_attempt_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()

        b_list = list_webhooks(db=self.db, tenant=self.tenant_b)
        self.assertEqual(len(b_list["data"]), 0)

        with self.assertRaises(HTTPException) as exc:
            update_webhook(
                endpoint_id=created.id,
                payload=WebhookPatch(label="hijack"),
                db=self.db,
                tenant=self.tenant_b,
            )
        self.assertEqual(exc.exception.status_code, 404)

        deliveries_b = list_deliveries(db=self.db, tenant=self.tenant_b)
        self.assertEqual(len(deliveries_b["data"]), 0)


if __name__ == "__main__":
    unittest.main()
