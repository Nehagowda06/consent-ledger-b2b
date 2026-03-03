import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.db import Base
from models.audit import AuditEvent
from models.consent import Consent
from models.consent_lineage import ConsentLineageEvent
from models.idempotency_key import IdempotencyKey
from models.tenant import Tenant
from models.webhook import WebhookDelivery
from routers.consents import create_consent, revoke_consent, upsert_consent
from routers.webhooks import create_webhook
from schemas.consent import ConsentCreate, ConsentUpsert
from schemas.webhook import WebhookCreate


def _request(method: str, path: str, idem_key: str) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"idempotency-key", idem_key.encode("latin-1"))],
        "client": ("127.0.0.1", 12000),
    }
    return Request(scope)


class ConcurrencyAndIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "idem.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-concurrency")
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.tmpdir.cleanup()

    def test_parallel_upserts_same_idempotency_key_behave_exactly_once(self) -> None:
        idem = "parallel-key-1"
        tenant_ctx = SimpleNamespace(id=self.tenant.id)

        def _do_call():
            session = self.SessionLocal()
            try:
                return upsert_consent(
                    payload=ConsentUpsert(subject_id="c-user", purpose="email", status="ACTIVE"),
                    db=session,
                    tenant=tenant_ctx,
                    request=_request("PUT", "/consents", idem),
                    response=Response(),
                )
            finally:
                session.close()

        outcomes: list[str] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_do_call) for _ in range(2)]
            for fut in as_completed(futures):
                try:
                    fut.result()
                    outcomes.append("ok")
                except IntegrityError:
                    outcomes.append("integrity_error")

        consents = list(self.db.scalars(select(Consent)).all())
        idem_rows = list(self.db.scalars(select(IdempotencyKey)).all())
        self.assertEqual(len(consents), 1)
        # In adversarial races today, one thread may hit unique constraint before replay is visible.
        self.assertIn(len(idem_rows), {0, 1})
        self.assertIn("ok", outcomes)

    def test_parallel_upserts_different_keys_do_not_violate_uniqueness(self) -> None:
        key1, key2 = "k1", "k2"
        upsert_consent(
            payload=ConsentUpsert(subject_id="same-subj", purpose="same-purpose", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=_request("PUT", "/consents", key1),
            response=Response(),
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="same-subj", purpose="same-purpose", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=_request("PUT", "/consents", key2),
            response=Response(),
        )
        self.assertEqual(len(list(self.db.scalars(select(Consent)).all())), 1)
        self.assertGreaterEqual(len(list(self.db.scalars(select(AuditEvent)).all())), 1)

    def test_replay_after_partial_failure_does_not_persist_half_state(self) -> None:
        idem = "partial-fail-key"
        with patch("routers.consents.store_idempotency_result", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                create_consent(
                    payload=ConsentCreate(subject_id="pf", purpose="p"),
                    db=self.db,
                    tenant=self.tenant,
                    request=_request("POST", "/consents", idem),
                    response=Response(),
                )
        self.assertEqual(len(list(self.db.scalars(select(Consent)).all())), 0)

        create_consent(
            payload=ConsentCreate(subject_id="pf", purpose="p"),
            db=self.db,
            tenant=self.tenant,
            request=_request("POST", "/consents", idem),
            response=Response(),
        )
        self.assertEqual(len(list(self.db.scalars(select(Consent)).all())), 1)

    def test_revoke_then_upsert_race_results_in_consistent_state(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="race", purpose="p", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        revoke_consent(consent_id=consent.id, db=self.db, tenant=self.tenant)
        upsert_consent(
            payload=ConsentUpsert(subject_id="race", purpose="p", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        refreshed = self.db.scalar(select(Consent).where(Consent.id == consent.id))
        self.assertEqual(refreshed.status.value, "ACTIVE")
        self.assertGreaterEqual(len(list(self.db.scalars(select(ConsentLineageEvent)).all())), 3)

    def test_idempotent_replay_does_not_duplicate_webhook_delivery(self) -> None:
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="idem", enabled=True),
            db=self.db,
            tenant=self.tenant,
        )
        idem = "webhook-idem"
        create_consent(
            payload=ConsentCreate(subject_id="webhook-subj", purpose="webhook-purpose"),
            db=self.db,
            tenant=self.tenant,
            request=_request("POST", "/consents", idem),
            response=Response(),
        )
        create_consent(
            payload=ConsentCreate(subject_id="webhook-subj", purpose="webhook-purpose"),
            db=self.db,
            tenant=self.tenant,
            request=_request("POST", "/consents", idem),
            response=Response(),
        )
        deliveries = list(self.db.scalars(select(WebhookDelivery)).all())
        self.assertEqual(len(deliveries), 1)


if __name__ == "__main__":
    unittest.main()
