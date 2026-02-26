import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.consent_proof import build_consent_proof
from core.db import Base
from models.api_key import ApiKey
from models.audit import AuditEvent
from models.system_event import SystemEvent
from models.tenant import Tenant, TenantLifecycleState
from routers.admin import disable_tenant, reactivate_tenant, suspend_tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class TenantLifecycleEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-lifecycle", is_active=True, lifecycle_state=TenantLifecycleState.ACTIVE)
        self.db.add(self.tenant)
        self.raw_key = "clb2b_lifecycle_key"
        self.db.add(ApiKey(tenant_id=self.tenant.id, key_hash=hash_api_key(self.raw_key), label="primary"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_active_tenant_can_write(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="s1", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        self.assertIsNotNone(consent.id)

    def test_suspended_tenant_cannot_write(self) -> None:
        self.tenant.lifecycle_state = TenantLifecycleState.SUSPENDED
        self.tenant.is_active = False
        self.db.add(self.tenant)
        self.db.commit()
        with self.assertRaises(HTTPException) as exc:
            upsert_consent(
                payload=ConsentUpsert(subject_id="s2", purpose="email", status="ACTIVE"),
                db=self.db,
                tenant=self.tenant,
            )
        self.assertEqual(exc.exception.status_code, 403)
        with self.assertRaises(HTTPException) as auth_exc:
            require_tenant(request=_request({"Authorization": f"Bearer {self.raw_key}"}), db=self.db)
        self.assertEqual(auth_exc.exception.status_code, 403)

    def test_disabled_tenant_cannot_write(self) -> None:
        self.tenant.lifecycle_state = TenantLifecycleState.DISABLED
        self.tenant.is_active = False
        self.db.add(self.tenant)
        self.db.commit()
        with self.assertRaises(HTTPException) as exc:
            upsert_consent(
                payload=ConsentUpsert(subject_id="s3", purpose="email", status="ACTIVE"),
                db=self.db,
                tenant=self.tenant,
            )
        self.assertEqual(exc.exception.status_code, 403)
        with self.assertRaises(HTTPException) as auth_exc:
            require_tenant(request=_request({"Authorization": f"Bearer {self.raw_key}"}), db=self.db)
        self.assertEqual(auth_exc.exception.status_code, 403)

    def test_historic_proofs_still_verify(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="s4", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=self.tenant.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
        )
        self.tenant.lifecycle_state = TenantLifecycleState.SUSPENDED
        self.tenant.is_active = False
        self.db.add(self.tenant)
        self.db.commit()
        from core.lineage_verify import verify_consent_proof

        result = verify_consent_proof(proof)
        self.assertTrue(result["verified"])

    def test_lifecycle_transitions_are_auditable(self) -> None:
        suspend_tenant(self.tenant.id, db=self.db)
        reactivate_tenant(self.tenant.id, db=self.db)
        disable_tenant(self.tenant.id, db=self.db)
        system_events = list(
            self.db.scalars(
                select(SystemEvent.event_type).where(SystemEvent.tenant_id == self.tenant.id)
            ).all()
        )
        self.assertIn("tenant.suspended", system_events)
        self.assertIn("tenant.reactivated", system_events)
        self.assertIn("tenant.disabled", system_events)
        audit_actions = list(
            self.db.scalars(
                select(AuditEvent.action).where(AuditEvent.tenant_id == self.tenant.id)
            ).all()
        )
        self.assertIn("tenant.suspended", audit_actions)
        self.assertIn("tenant.reactivated", audit_actions)
        self.assertIn("tenant.disabled", audit_actions)

    def test_enforcement_is_fail_closed(self) -> None:
        with patch("routers.admin.record_system_event", side_effect=RuntimeError("event failure")):
            with self.assertRaises(RuntimeError):
                suspend_tenant(self.tenant.id, db=self.db)
        refreshed = self.db.get(Tenant, self.tenant.id)
        self.assertEqual(refreshed.lifecycle_state, TenantLifecycleState.ACTIVE)
        self.assertTrue(refreshed.is_active)


if __name__ == "__main__":
    unittest.main()

