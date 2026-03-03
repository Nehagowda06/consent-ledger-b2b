import asyncio
import unittest
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from core.idempotency import build_request_hash, check_idempotency, store_idempotency_result
from core.identity_crypto import compute_identity_fingerprint
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_exported_lineage
from core.system_proof import verify_system_proof
from core.db import Base
from models.tenant import Tenant
from routers.anchors import verify_snapshot
from routers.consents import list_consents, upsert_consent
from routers.lineage_verify import verify_lineage_export
from routers.proofs import verify_proof
from routers.system_verify import verify_system_proof_endpoint
from schemas.consent import ConsentUpsert


def _request_with_body(body: bytes, path: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 19001),
    }
    request = Request(scope)

    async def _body():
        return body

    request.body = _body  # type: ignore[assignment]
    return request


class ExtremeAdversarialCampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-extreme-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-extreme-b")
        self.db.add_all([self.tenant_a, self.tenant_b])
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_sql_injection_style_subject_id_is_literal_and_tenant_scoped(self) -> None:
        injection_subject = "' OR 1=1 --"
        upsert_consent(
            payload=ConsentUpsert(subject_id=injection_subject, purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="normal", purpose="sms", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id=injection_subject, purpose="other", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_b,
        )

        res_a = list_consents(subject_id=injection_subject, db=self.db, tenant=self.tenant_a)
        self.assertEqual(res_a["meta"]["count"], 1)
        self.assertEqual(len(res_a["data"]), 1)
        self.assertEqual(res_a["data"][0].subject_id, injection_subject)

    def test_duplicate_json_keys_are_rejected_on_public_verifiers(self) -> None:
        dup = b'{"version":1,"version":2}'
        req_lineage = _request_with_body(dup, "/lineage/verify")
        req_proofs = _request_with_body(dup, "/proofs/verify")
        req_anchors = _request_with_body(dup, "/anchors/verify")
        req_system = _request_with_body(dup, "/system/verify")

        async def _run():
            with self.assertRaises(RequestValidationError):
                await verify_lineage_export(request=req_lineage, export={})
            with self.assertRaises(RequestValidationError):
                await verify_proof(request=req_proofs, proof={})
            with self.assertRaises(RequestValidationError):
                await verify_snapshot(request=req_anchors, snapshot={})
            with self.assertRaises(RequestValidationError):
                await verify_system_proof_endpoint(request=req_system, proof={})

        asyncio.run(_run())

    def test_tampered_signed_lineage_reports_signature_failure_first(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="sig-user", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        private_key = Ed25519PrivateKey.generate()
        private_hex = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ).hex()
        public_hex = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()
        fingerprint = compute_identity_fingerprint(public_hex)

        artifact = export_consent_lineage(
            consent.id,
            self.tenant_a.id,
            self.db,
            signer_identity_fingerprint=fingerprint,
            signer_public_key=public_hex,
            signer_private_key_hex=private_hex,
        )
        artifact["signature"] = artifact["signature"][:-2]
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertIn("signature", str(result["failure_reason"]).lower())

    def test_idempotency_replay_with_different_request_hash_conflicts(self) -> None:
        key = "extreme-idem-key"
        req_hash_a = build_request_hash("PUT", "/consents", {"subject_id": "a", "purpose": "p", "status": "ACTIVE"})
        req_hash_b = build_request_hash("PUT", "/consents", {"subject_id": "b", "purpose": "p", "status": "ACTIVE"})
        store_idempotency_result(
            db=self.db,
            tenant_id=self.tenant_a.id,
            key=key,
            request_hash=req_hash_a,
            response_json={"ok": True},
            status_code=200,
        )
        self.db.commit()
        with self.assertRaises(HTTPException) as exc:
            check_idempotency(self.db, self.tenant_a.id, key, req_hash_b)
        self.assertEqual(exc.exception.status_code, 409)
        self.assertIn("Idempotency-Key reuse with different request", str(exc.exception.detail))

    def test_system_proof_structure_tampering_is_deterministic(self) -> None:
        result = verify_system_proof(
            {
                "version": 1,
                "generated_at": "2026-02-26T00:00:00Z",
                "event_count": 1,
                "last_event_hash": "0" * 64,
                "events": [{"event_type": "x"}],
            }
        )
        self.assertFalse(result["verified"])
        self.assertIn("invalid event_hash", str(result["failure_reason"]).lower())


if __name__ == "__main__":
    unittest.main()
