import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.admin_auth import require_admin
from core.api_keys import hash_api_key
from core.auth import require_tenant
from core.db import Base
from core.lineage_verify import verify_consent_proof
from models.api_key import ApiKey
from models.tenant import Tenant
from routers.consents import (
    create_consent_proof,
    get_consent,
    get_consent_lineage_export,
    upsert_consent,
)
from schemas.consent import ConsentUpsert


def make_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class AdversarialAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-auth-a", is_active=True)
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-auth-b", is_active=True)
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.tenant_a_key = "clb2b_tenant_a_key"
        self.tenant_b_key = "clb2b_tenant_b_key"
        self.admin_key = "admin-secret"
        self.db.add(ApiKey(tenant_id=self.tenant_a.id, key_hash=hash_api_key(self.tenant_a_key), label="a"))
        self.db.add(ApiKey(tenant_id=self.tenant_b.id, key_hash=hash_api_key(self.tenant_b_key), label="b"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_cross_tenant_access_by_guessed_uuid_is_404(self) -> None:
        created = upsert_consent(
            payload=ConsentUpsert(subject_id="x", purpose="p", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        with self.assertRaises(HTTPException) as exc:
            get_consent(consent_id=created.id, db=self.db, tenant=self.tenant_b)
        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Consent not found")

    def test_cross_tenant_lineage_export_and_proof_are_404(self) -> None:
        created = upsert_consent(
            payload=ConsentUpsert(subject_id="x2", purpose="p2", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        with self.assertRaises(HTTPException) as lineage_exc:
            get_consent_lineage_export(
                consent_id=created.id,
                response=Response(),
                db=self.db,
                tenant=self.tenant_b,
            )
        with self.assertRaises(HTTPException) as proof_exc:
            create_consent_proof(
                consent_id=created.id,
                payload=types.SimpleNamespace(asserted_at=datetime.now(timezone.utc)),
                response=Response(),
                db=self.db,
                tenant=self.tenant_b,
            )
        self.assertEqual(lineage_exc.exception.status_code, 404)
        self.assertEqual(proof_exc.exception.status_code, 404)

    def test_replayed_proof_with_tenant_swap_fails_without_leak(self) -> None:
        created = upsert_consent(
            payload=ConsentUpsert(subject_id="u3", purpose="p3", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        proof = create_consent_proof(
            consent_id=created.id,
            payload=types.SimpleNamespace(asserted_at=datetime.now(timezone.utc)),
            response=Response(),
            db=self.db,
            tenant=self.tenant_a,
        )
        proof["tenant_id"] = str(self.tenant_b.id)
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])
        self.assertIn("tenant", result["failure_reason"])

    def test_revoked_key_mid_request_is_rejected(self) -> None:
        key_row = self.db.query(ApiKey).filter(ApiKey.tenant_id == self.tenant_a.id).first()
        request = make_request({"Authorization": f"Bearer {self.tenant_a_key}"})

        original = key_row.revoked_at

        def _lookup(*_args, **_kwargs):
            key_row.revoked_at = datetime.now(timezone.utc)
            return key_row

        with patch("core.auth._get_api_key_record", side_effect=_lookup):
            with self.assertRaises(HTTPException) as exc:
                require_tenant(request=request, db=self.db)
        key_row.revoked_at = original
        self.assertEqual(exc.exception.status_code, 401)

    def test_admin_and_tenant_key_misuse_rejected(self) -> None:
        with patch("core.admin_auth.settings", new=types.SimpleNamespace(admin_api_key=self.admin_key)):
            with self.assertRaises(HTTPException) as admin_on_tenant_exc:
                require_tenant(
                    request=make_request({"Authorization": f"Bearer {self.admin_key}"}),
                    db=self.db,
                )
            with self.assertRaises(HTTPException) as tenant_on_admin_exc:
                require_admin(self.tenant_a_key)
        self.assertEqual(admin_on_tenant_exc.exception.status_code, 401)
        self.assertEqual(tenant_on_admin_exc.exception.status_code, 401)

    def test_disabled_tenant_cannot_access_reads_proof_or_lineage(self) -> None:
        created = upsert_consent(
            payload=ConsentUpsert(subject_id="u4", purpose="p4", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        self.tenant_a.is_active = False
        self.db.add(self.tenant_a)
        self.db.commit()

        with self.assertRaises(HTTPException) as exc:
            require_tenant(
                request=make_request({"Authorization": f"Bearer {self.tenant_a_key}"}),
                db=self.db,
            )
        self.assertEqual(exc.exception.status_code, 403)

        # Route-level isolation still returns not found for wrong tenant.
        with self.assertRaises(HTTPException):
            get_consent_lineage_export(created.id, Response(), self.db, self.tenant_b)
        with self.assertRaises(HTTPException):
            create_consent_proof(
                created.id,
                types.SimpleNamespace(asserted_at=datetime.now(timezone.utc)),
                Response(),
                self.db,
                self.tenant_b,
            )

    def test_constant_time_compare_paths_are_used(self) -> None:
        request = make_request({"Authorization": f"Bearer {self.tenant_a_key}"})
        with patch("core.auth.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as auth_cmp:
            require_tenant(request=request, db=self.db)
            self.assertGreaterEqual(auth_cmp.call_count, 1)
        with patch("core.admin_auth.settings", new=types.SimpleNamespace(admin_api_key=self.admin_key)):
            with patch("core.admin_auth.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as admin_cmp:
                require_admin(self.admin_key)
                self.assertGreaterEqual(admin_cmp.call_count, 1)


if __name__ == "__main__":
    unittest.main()
