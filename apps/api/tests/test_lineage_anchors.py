import unittest
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.lineage import compute_event_hash
from core.lineage_anchor import compute_tenant_anchor
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from models.api_key import ApiKey
from models.tenant import Tenant
from routers.consents import get_consent_lineage_export, upsert_consent
from schemas.consent import ConsentUpsert


class LineageAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-anchor-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-anchor-b")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="anchor-user", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="anchor-user", purpose="email", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_a,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_anchor_stable_across_api_key_rotation(self) -> None:
        artifact_before = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)

        # Simulate API key rotation by revoking one key and adding another.
        self.db.add(
            ApiKey(tenant_id=self.tenant_a.id, key_hash="hash-one", label="k1")
        )
        self.db.flush()
        self.db.add(
            ApiKey(tenant_id=self.tenant_a.id, key_hash="hash-two", label="k2")
        )
        self.db.commit()

        artifact_after = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        self.assertEqual(artifact_before["tenant_anchor"], artifact_after["tenant_anchor"])

    def test_tampered_lineage_root_fails_anchor_verification(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        last = artifact["events"][-1]
        prev = artifact["events"][-2]["event_hash"] if len(artifact["events"]) > 1 else None
        last["action"] = "noop"
        last["event_hash"] = compute_event_hash(
            {
                "tenant_id": artifact["tenant_id"],
                "consent_id": artifact["consent_id"],
                "action": "noop",
                "payload": {},
            },
            prev,
        )
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertFalse(result["anchor_verified"])
        self.assertIn("tenant_anchor mismatch", result["failure_reason"])

    def test_anchor_mismatch_fails_proof_verification(self) -> None:
        proof = build_consent_proof(
            consent_id=self.consent.id,
            tenant_id=self.tenant_a.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
        )
        proof["tenant_anchor"] = "0" * 64
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])
        self.assertIn("tenant_anchor", result["failure_reason"])

    def test_offline_anchor_verification_without_db(self) -> None:
        tenant_id = str(uuid.uuid4())
        consent_id = str(uuid.uuid4())
        e1 = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "created", "payload": {}},
            None,
        )
        e2 = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "revoked", "payload": {}},
            e1,
        )
        export = {
            "version": 1,
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "algorithm": "SHA256",
            "canonicalization": "sorted-json-no-whitespace",
            "tenant_anchor": compute_tenant_anchor(tenant_id, e2),
            "events": [
                {"action": "created", "event_hash": e1, "prev_event_hash": None, "created_at": "2026-02-24T00:00:00Z"},
                {"action": "revoked", "event_hash": e2, "prev_event_hash": e1, "created_at": "2026-02-25T00:00:00Z"},
            ],
        }
        result = verify_exported_lineage(export)
        self.assertTrue(result["verified"])
        self.assertTrue(result["anchor_verified"])

    def test_tenant_isolation_preserved_for_exports(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            get_consent_lineage_export(
                consent_id=self.consent.id,
                response=Response(),
                db=self.db,
                tenant=self.tenant_b,
            )
        self.assertEqual(exc.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
