import asyncio
import os
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import main
from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.db import Base
from core.rate_limit import SQLiteRateLimiter
from core.webhooks import process_pending_deliveries
from models.api_key import ApiKey
from models.system_event import SystemEvent
from models.tenant import Tenant
from routers.admin import (
    create_anchor_snapshot,
    create_api_key,
    create_tenant,
    disable_tenant,
    revoke_api_key,
)
from routers.consents import upsert_consent
from routers.webhooks import create_webhook
from schemas.admin import ApiKeyCreateIn, TenantCreateIn
from schemas.consent import ConsentUpsert
from schemas.webhook import WebhookCreate


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 13000),
    }
    return Request(scope)


class SystemEventRecordingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_admin_actions_record_events(self) -> None:
        tenant_out = create_tenant(payload=TenantCreateIn(name="tenant-admin-events"), db=self.db)
        key_out = create_api_key(
            tenant_id=tenant_out.id,
            payload=ApiKeyCreateIn(label="automation"),
            db=self.db,
        )
        revoke_api_key(api_key_id=key_out.id, db=self.db)
        disable_tenant(tenant_id=tenant_out.id, db=self.db)
        create_anchor_snapshot(response=types.SimpleNamespace(headers={}), db=self.db)

        event_types = list(
            self.db.scalars(
                select(SystemEvent.event_type).order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc())
            ).all()
        )
        self.assertIn("admin.tenant.create", event_types)
        self.assertIn("admin.api_key.create", event_types)
        self.assertIn("admin.api_key.revoke", event_types)
        self.assertIn("admin.tenant.disable", event_types)
        self.assertIn("admin.external_anchor.snapshot", event_types)

    def test_admin_create_tenant_rolls_back_when_event_recording_fails(self) -> None:
        with patch("routers.admin.record_system_event", side_effect=RuntimeError("ledger write failed")):
            with self.assertRaises(RuntimeError):
                create_tenant(payload=TenantCreateIn(name="tenant-rollback"), db=self.db)

        created = self.db.scalar(select(Tenant).where(Tenant.name == "tenant-rollback"))
        self.assertIsNone(created)

    def test_admin_create_api_key_rolls_back_when_event_recording_fails(self) -> None:
        tenant = create_tenant(payload=TenantCreateIn(name="tenant-key-rollback"), db=self.db)
        with patch("routers.admin.record_system_event", side_effect=RuntimeError("ledger write failed")):
            with self.assertRaises(RuntimeError):
                create_api_key(tenant_id=tenant.id, payload=ApiKeyCreateIn(label="should-not-persist"), db=self.db)

        key = self.db.scalar(select(ApiKey).where(ApiKey.label == "should-not-persist"))
        self.assertIsNone(key)

    def test_rate_limit_exceeded_records_event(self) -> None:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-rate", is_active=True)
        raw_key = "clb2b_rate_limit_event"
        self.db.add(tenant)
        self.db.add(ApiKey(tenant_id=tenant.id, key_hash=hash_api_key(raw_key), label="rl"))
        self.db.commit()

        db_path = str(Path(tempfile.gettempdir()) / f"rl-{uuid.uuid4().hex}.sqlite3")
        limiter = SQLiteRateLimiter(db_path=db_path, limit_per_minute=1)
        request = _request({"Authorization": f"Bearer {raw_key}"})
        with patch("core.auth.RATE_LIMITER", limiter):
            require_tenant(request=request, db=self.db)
            with self.assertRaises(HTTPException) as exc:
                require_tenant(request=request, db=self.db)
            self.assertEqual(exc.exception.status_code, 429)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass

        event = self.db.scalar(
            select(SystemEvent).where(SystemEvent.event_type == "auth.rate_limit.exceeded")
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.tenant_id, tenant.id)

    def test_webhook_delivery_attempt_records_event(self) -> None:
        tenant = Tenant(id=uuid.uuid4(), name="tenant-webhook-event")
        self.db.add(tenant)
        self.db.commit()
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9001/hook", label="ops", enabled=True),
            db=self.db,
            tenant=tenant,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="subject-wh", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=tenant,
        )
        with patch("core.webhooks.send_webhook_http", return_value=500):
            processed = process_pending_deliveries(self.db, tenant_id=tenant.id)
        self.assertGreaterEqual(processed, 1)

        event = self.db.scalar(
            select(SystemEvent).where(SystemEvent.event_type == "webhook.delivery.attempt")
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.tenant_id, tenant.id)

    def test_startup_records_event(self) -> None:
        def _session_factory():
            return self.SessionLocal()

        fake_settings = types.SimpleNamespace(
            env="dev",
            version_hash="test-sha",
            expected_alembic_head=None,
            auto_create_schema=False,
            database_url="sqlite://",
            api_key_hash_secret="dev-secret",
            webhook_signing_secret="dev-secret",
            admin_api_key="admin-dev-key",
            cors_allowed_origins=["http://localhost:3000"],
            api_key_rate_limit_per_min=10,
        )
        fake_app = types.SimpleNamespace(state=types.SimpleNamespace())

        with patch("main.SessionLocal", new=_session_factory):
            with patch("main.settings", new=fake_settings):
                with patch("main._current_alembic_heads", return_value="head-test"):
                    with patch("main.start_webhook_worker", return_value=None):
                        asyncio.run(main.on_startup())

        event = self.db.scalar(select(SystemEvent).where(SystemEvent.event_type == "app.startup"))
        self.assertIsNotNone(event)


if __name__ == "__main__":
    unittest.main()
