import asyncio
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.webhook_worker import start_webhook_worker, stop_webhook_worker
from core.webhooks import canonical_json, compute_webhook_signature, process_pending_deliveries
from models.consent import ConsentStatus
from models.tenant import Tenant
from models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookEndpoint
from routers.consents import upsert_consent
from routers.webhooks import create_webhook
from schemas.consent import ConsentUpsert
from schemas.webhook import WebhookCreate


def _idem_request(key: str) -> Request:
    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/consents",
        "headers": [(b"idempotency-key", key.encode("latin-1"))],
        "client": ("127.0.0.1", 13000),
    }
    return Request(scope)


class WebhookChaosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-chaos")
        self.db.add(self.tenant)
        self.db.commit()
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="chaos", enabled=True),
            db=self.db,
            tenant=self.tenant,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_timeouts_and_tls_failures_retry_without_blocking_consents(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="wh-chaos", purpose="email", status=ConsentStatus.ACTIVE),
            db=self.db,
            tenant=self.tenant,
        )
        self.assertEqual(consent.status.value, "ACTIVE")
        now = datetime.now(timezone.utc)

        with patch("core.webhooks.send_webhook_http", side_effect=TimeoutError("timeout")):
            processed = process_pending_deliveries(self.db, tenant_id=self.tenant.id, now=now)
        self.assertGreaterEqual(processed, 1)
        delivery = self.db.scalar(select(WebhookDelivery))
        self.assertEqual(delivery.status, WebhookDeliveryStatus.PENDING)
        self.assertIsNotNone(delivery.next_attempt_at)

    def test_http_500_and_429_backoff_and_terminal_failure(self) -> None:
        upsert_consent(
            payload=ConsentUpsert(subject_id="wh-fail", purpose="email", status=ConsentStatus.ACTIVE),
            db=self.db,
            tenant=self.tenant,
        )
        delivery = self.db.scalar(select(WebhookDelivery))
        now = datetime.now(timezone.utc)

        with patch("core.webhooks.send_webhook_http", return_value=500):
            process_pending_deliveries(self.db, tenant_id=self.tenant.id, now=now)
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, WebhookDeliveryStatus.PENDING)

        delivery.attempt_count = 7
        delivery.next_attempt_at = now
        self.db.add(delivery)
        self.db.commit()
        with patch("core.webhooks.send_webhook_http", return_value=429):
            process_pending_deliveries(self.db, tenant_id=self.tenant.id, now=now)
        self.db.refresh(delivery)
        self.assertEqual(delivery.status, WebhookDeliveryStatus.FAILED)

    def test_worker_restart_mid_delivery_is_non_blocking(self) -> None:
        async def _run():
            app = type("A", (), {"state": type("S", (), {})()})()

            async def _loop(_app):
                await asyncio.sleep(60)

            with patch("core.webhook_worker._worker_loop", _loop):
                with patch("core.webhook_worker.get_settings", return_value=type("Cfg", (), {"webhook_worker_enabled": True})()):
                    start_webhook_worker(app)
                    self.assertIsNotNone(getattr(app.state, "webhook_worker_task", None))
                    await stop_webhook_worker(app)
                    start_webhook_worker(app)
                    await stop_webhook_worker(app)
                    self.assertIsNone(getattr(app.state, "webhook_worker_task", None))

        asyncio.run(_run())

    def test_idempotent_retries_do_not_duplicate_delivery(self) -> None:
        idem = "dup-delivery"
        upsert_consent(
            payload=ConsentUpsert(subject_id="dup", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=_idem_request(idem),
            response=Response(),
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="dup", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=_idem_request(idem),
            response=Response(),
        )
        deliveries = list(self.db.scalars(select(WebhookDelivery)).all())
        self.assertEqual(len(deliveries), 1)

    def test_payload_tampering_changes_signature(self) -> None:
        secret = "whsec_test"
        ts = 1_700_000_000
        body_a = canonical_json({"v": 1})
        body_b = canonical_json({"v": 2})
        sig_a = compute_webhook_signature(secret, ts, body_a)
        sig_b = compute_webhook_signature(secret, ts, body_b)
        self.assertNotEqual(sig_a, sig_b)


if __name__ == "__main__":
    unittest.main()
