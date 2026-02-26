import unittest
import uuid
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.db import Base
from models.api_key import ApiKey
from models.audit import AuditEvent
from models.consent import Consent
from models.idempotency_key import IdempotencyKey
from models.tenant import Tenant
from routers.consents import upsert_consent
from routers.webhooks import create_webhook
from schemas.consent import ConsentUpsert
from schemas.webhook import WebhookCreate


def make_request(method: str, path: str, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class AuthIdempotencyFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-flow")
        self.db.add(self.tenant)
        self.raw_key = "clb2b_test_key"
        self.db.add(
            ApiKey(
                tenant_id=self.tenant.id,
                key_hash=hash_api_key(self.raw_key),
                label="flow-key",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    @patch("core.webhooks.send_webhook_http")
    def test_upsert_idempotency_under_auth_and_no_outbound(self, mock_send) -> None:
        create_webhook(
            payload=WebhookCreate(url="http://localhost:9000/hook", label="flow", enabled=True),
            db=self.db,
            tenant=self.tenant,
        )

        headers = {
            "Authorization": f"Bearer {self.raw_key}",
            "Idempotency-Key": "idem-flow-1",
        }
        request = make_request("PUT", "/consents", headers)
        tenant_ctx = require_tenant(request=request, db=self.db)

        first = upsert_consent(
            payload=ConsentUpsert(subject_id="subject-flow", purpose="marketing", status="ACTIVE"),
            db=self.db,
            tenant=tenant_ctx,
            request=request,
            response=Response(),
        )
        second = upsert_consent(
            payload=ConsentUpsert(subject_id="subject-flow", purpose="marketing", status="ACTIVE"),
            db=self.db,
            tenant=tenant_ctx,
            request=make_request("PUT", "/consents", headers),
            response=Response(),
        )

        first_id = str(first["id"]) if isinstance(first, dict) else str(first.id)
        second_id = str(second["id"]) if isinstance(second, dict) else str(second.id)
        self.assertEqual(first_id, second_id)

        consents = list(self.db.scalars(select(Consent)).all())
        audits = list(self.db.scalars(select(AuditEvent)).all())
        idem = list(self.db.scalars(select(IdempotencyKey)).all())
        self.assertEqual(len(consents), 1)
        self.assertEqual(len(idem), 1)
        self.assertEqual(len(audits), 1)
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
