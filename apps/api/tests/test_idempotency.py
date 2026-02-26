import unittest
import uuid

from fastapi import HTTPException, Response
from starlette.requests import Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.audit import AuditEvent
from models.consent import Consent
from models.idempotency_key import IdempotencyKey
from models.tenant import Tenant
from routers.consents import create_consent, upsert_consent
from schemas.consent import ConsentCreate, ConsentUpsert


def make_request(method: str, path: str, idem_key: str) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"idempotency-key", idem_key.encode("latin-1"))],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class IdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-idempotency")
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_upsert_replay_returns_stored_without_extra_writes(self) -> None:
        key = "idem-upsert-1"
        request_1 = make_request("PUT", "/consents", key)
        request_2 = make_request("PUT", "/consents", key)
        response_1 = Response()
        response_2 = Response()

        first = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-a", purpose="marketing", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=request_1,
            response=response_1,
        )
        second = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-a", purpose="marketing", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=request_2,
            response=response_2,
        )

        first_id = str(first["id"]) if isinstance(first, dict) else str(first.id)
        second_id = str(second["id"]) if isinstance(second, dict) else str(second.id)
        self.assertEqual(first_id, second_id)
        self.assertEqual(response_2.status_code, 200)

        consents = list(self.db.scalars(select(Consent)).all())
        audits = list(self.db.scalars(select(AuditEvent)).all())
        idempotency_rows = list(self.db.scalars(select(IdempotencyKey)).all())
        self.assertEqual(len(consents), 1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(len(idempotency_rows), 1)

    def test_upsert_same_key_different_body_returns_409(self) -> None:
        key = "idem-upsert-2"
        upsert_consent(
            payload=ConsentUpsert(subject_id="subj-b", purpose="analytics", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
            request=make_request("PUT", "/consents", key),
            response=Response(),
        )

        with self.assertRaises(HTTPException) as exc:
            upsert_consent(
                payload=ConsentUpsert(subject_id="subj-b", purpose="analytics", status="REVOKED"),
                db=self.db,
                tenant=self.tenant,
                request=make_request("PUT", "/consents", key),
                response=Response(),
            )
        self.assertEqual(exc.exception.status_code, 409)

    def test_create_replay_returns_stored_without_duplicates(self) -> None:
        key = "idem-create-1"
        create_consent(
            payload=ConsentCreate(subject_id="subj-c", purpose="product_updates"),
            db=self.db,
            tenant=self.tenant,
            request=make_request("POST", "/consents", key),
            response=Response(),
        )
        create_consent(
            payload=ConsentCreate(subject_id="subj-c", purpose="product_updates"),
            db=self.db,
            tenant=self.tenant,
            request=make_request("POST", "/consents", key),
            response=Response(),
        )

        consents = list(self.db.scalars(select(Consent)).all())
        audits = list(self.db.scalars(select(AuditEvent)).all())
        self.assertEqual(len(consents), 1)
        self.assertEqual(len(audits), 1)


if __name__ == "__main__":
    unittest.main()
