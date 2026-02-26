import unittest
import uuid
import sys
import types
from unittest.mock import patch

from fastapi import Response
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.failure_modes import classify_failure, failure_policy, FailureClass
from core.identity_crypto import compute_identity_fingerprint
from core.webhooks import process_pending_deliveries
from models.audit import AuditEvent
from models.consent import Consent
from models.consent_lineage import ConsentLineageEvent
from models.identity_key import IdentityKey, IdentityKeyScope
from models.signed_assertion import SignedAssertion
from models.system_event import SystemEvent
from models.tenant import Tenant
from models.webhook import WebhookDelivery, WebhookDeliveryStatus
from schemas.consent import ConsentCreate, ConsentUpsert
from schemas.webhook import WebhookCreate


def _install_cryptography_stub() -> None:
    if "cryptography.hazmat.primitives.asymmetric.ed25519" in sys.modules:
        return

    class _FakePrivateKey:
        @staticmethod
        def from_private_bytes(_value):
            return _FakePrivateKey()

        def sign(self, message: bytes) -> bytes:
            return (message[:32] + b"\x00" * 32)[:64]

    class _FakePublicKey:
        @staticmethod
        def from_public_bytes(_value):
            return _FakePublicKey()

        def verify(self, signature: bytes, message: bytes) -> None:
            expected = (message[:32] + b"\x00" * 32)[:64]
            if signature != expected:
                raise ValueError("invalid signature")

    crypto_mod = types.ModuleType("cryptography")
    hazmat_mod = types.ModuleType("cryptography.hazmat")
    primitives_mod = types.ModuleType("cryptography.hazmat.primitives")
    asym_mod = types.ModuleType("cryptography.hazmat.primitives.asymmetric")
    ed_mod = types.ModuleType("cryptography.hazmat.primitives.asymmetric.ed25519")
    ed_mod.Ed25519PrivateKey = _FakePrivateKey
    ed_mod.Ed25519PublicKey = _FakePublicKey

    sys.modules["cryptography"] = crypto_mod
    sys.modules["cryptography.hazmat"] = hazmat_mod
    sys.modules["cryptography.hazmat.primitives"] = primitives_mod
    sys.modules["cryptography.hazmat.primitives.asymmetric"] = asym_mod
    sys.modules["cryptography.hazmat.primitives.asymmetric.ed25519"] = ed_mod


_install_cryptography_stub()

from routers.consents import create_consent, upsert_consent
from routers.webhooks import create_webhook


def _request(method: str, path: str, idem_key: str) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"idempotency-key", idem_key.encode("latin-1"))],
        "client": ("127.0.0.1", 14000),
    }
    return Request(scope)


class OperationalFailureAtomicityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-ops", is_active=True)
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_db_exception_mid_write_rolls_back_all_rows(self) -> None:
        with patch("routers.consents.enqueue_webhook_event", side_effect=RuntimeError("db unavailable")):
            with self.assertRaises(RuntimeError):
                create_consent(
                    payload=ConsentCreate(subject_id="mid-write", purpose="email"),
                    db=self.db,
                    tenant=self.tenant,
                    request=_request("POST", "/consents", "db-fail-1"),
                    response=Response(),
                )

        self.assertEqual(len(list(self.db.scalars(select(Consent)).all())), 0)
        self.assertEqual(len(list(self.db.scalars(select(AuditEvent)).all())), 0)
        self.assertEqual(len(list(self.db.scalars(select(ConsentLineageEvent)).all())), 0)

    def test_signature_failure_prevents_assertion_persist(self) -> None:
        public_key_hex = "ab" * 32
        identity_key = IdentityKey(
            scope=IdentityKeyScope.SYSTEM,
            owner_id=None,
            public_key=public_key_hex,
            fingerprint=compute_identity_fingerprint(public_key_hex),
        )
        self.db.add(identity_key)
        self.db.commit()

        def _create_assertion() -> None:
            raise ValueError("signature.failed")
        with self.assertRaises(ValueError):
            try:
                _create_assertion()
            except Exception:
                self.db.rollback()
                raise

        self.assertEqual(len(list(self.db.scalars(select(SignedAssertion)).all())), 0)

    def test_exception_after_lineage_append_before_commit_rolls_back(self) -> None:
        with patch("routers.consents.store_idempotency_result", side_effect=RuntimeError("serialization.failed")):
            with self.assertRaises(RuntimeError):
                upsert_consent(
                    payload=ConsentUpsert(subject_id="lineage-fail", purpose="email", status="ACTIVE"),
                    db=self.db,
                    tenant=self.tenant,
                    request=_request("PUT", "/consents", "lineage-rollback-1"),
                    response=Response(),
                )

        self.assertEqual(len(list(self.db.scalars(select(Consent)).all())), 0)
        self.assertEqual(len(list(self.db.scalars(select(ConsentLineageEvent)).all())), 0)

    def test_background_retry_duplicate_execution_is_safe(self) -> None:
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9500/hook", label="ops", enabled=True),
            db=self.db,
            tenant=self.tenant,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="dup-safe", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=_request("PUT", "/consents", "dup-safe-1"),
            response=Response(),
        )

        with patch("core.webhooks.send_webhook_http", return_value=200):
            first = process_pending_deliveries(self.db, tenant_id=self.tenant.id)
            second = process_pending_deliveries(self.db, tenant_id=self.tenant.id)

        delivery = self.db.scalar(select(WebhookDelivery))
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.status, WebhookDeliveryStatus.SENT)
        self.assertEqual(delivery.attempt_count, 1)

    def test_failed_operation_is_recorded_as_system_event(self) -> None:
        with patch("routers.consents.enqueue_webhook_event", side_effect=RuntimeError("db unavailable")):
            with self.assertRaises(RuntimeError):
                create_consent(
                    payload=ConsentCreate(subject_id="event-failure", purpose="email"),
                    db=self.db,
                    tenant=self.tenant,
                    request=_request("POST", "/consents", "event-fail-1"),
                    response=Response(),
                )

        event = self.db.scalar(
            select(SystemEvent).where(SystemEvent.event_type == "consent.create.failed")
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.tenant_id, self.tenant.id)

    def test_failure_classification_is_deterministic(self) -> None:
        integrity_exc = IntegrityError("stmt", {}, Exception("constraint"))
        sig_exc = ValueError("signature verification failed")
        ser_exc = ValueError("serialization.failed")
        unknown_exc = RuntimeError("boom")

        self.assertEqual(classify_failure(integrity_exc), FailureClass.DB_CONSTRAINT_VIOLATION)
        self.assertEqual(failure_policy(integrity_exc).http_status, 409)
        self.assertEqual(classify_failure(sig_exc), FailureClass.SIGNATURE_FAILED)
        self.assertEqual(failure_policy(sig_exc).http_status, 422)
        self.assertEqual(classify_failure(ser_exc), FailureClass.SERIALIZATION_FAILED)
        self.assertEqual(failure_policy(ser_exc).http_status, 422)
        self.assertEqual(classify_failure(unknown_exc), FailureClass.UNEXPECTED_EXCEPTION)
        self.assertEqual(failure_policy(unknown_exc).http_status, 500)


if __name__ == "__main__":
    unittest.main()
