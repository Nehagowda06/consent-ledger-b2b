import unittest
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.lineage_verify import verify_consent_proof
from core.lineage import compute_event_hash
from core.lineage_anchor import compute_tenant_anchor
from core.lineage_export import export_consent_lineage
from models.tenant import Tenant
from routers.consents import create_consent_proof, upsert_consent
from schemas.consent import ConsentUpsert


class ConsentProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-proof-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-proof-b")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _create_active_consent(self):
        return upsert_consent(
            payload=ConsentUpsert(subject_id="proof-subj", purpose="email", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )

    def _asserted_at_last_event(self, consent_id):
        artifact = export_consent_lineage(consent_id, self.tenant_a.id, self.db)
        last_ts = artifact["events"][-1]["created_at"]
        return datetime.fromisoformat(last_ts.replace("Z", "+00:00"))

    def test_proof_verifies_for_active(self) -> None:
        consent = self._create_active_consent()
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=self.tenant_a.id,
            asserted_at=self._asserted_at_last_event(consent.id),
            db=self.db,
        )
        result = verify_consent_proof(proof)
        self.assertTrue(result["verified"])
        self.assertEqual(result["derived_state"], "ACTIVE")

    def test_proof_verifies_for_revoked(self) -> None:
        consent = self._create_active_consent()
        upsert_consent(
            payload=ConsentUpsert(subject_id="proof-subj", purpose="email", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_a,
        )
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=self.tenant_a.id,
            asserted_at=self._asserted_at_last_event(consent.id),
            db=self.db,
        )
        result = verify_consent_proof(proof)
        self.assertTrue(result["verified"])
        self.assertEqual(result["derived_state"], "REVOKED")

    def test_tampered_included_events_fails(self) -> None:
        consent = self._create_active_consent()
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=self.tenant_a.id,
            asserted_at=self._asserted_at_last_event(consent.id),
            db=self.db,
        )
        proof["included_events"][0]["event_hash"] = "a" * 64
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])

    def test_tampered_asserted_state_fails(self) -> None:
        consent = self._create_active_consent()
        proof = build_consent_proof(
            consent_id=consent.id,
            tenant_id=self.tenant_a.id,
            asserted_at=self._asserted_at_last_event(consent.id),
            db=self.db,
        )
        proof["asserted_state"] = "REVOKED"
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])

    def test_missing_events_before_asserted_at_fails(self) -> None:
        consent = self._create_active_consent()
        before_first = datetime.now(timezone.utc) - timedelta(days=3650)
        with self.assertRaises(ValueError):
            build_consent_proof(
                consent_id=consent.id,
                tenant_id=self.tenant_a.id,
                asserted_at=before_first,
                db=self.db,
            )

    def test_offline_verification_without_db(self) -> None:
        tenant_id = str(uuid.uuid4())
        consent_id = str(uuid.uuid4())
        event_hash = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "created", "payload": {}},
            None,
        )
        tenant_anchor = compute_tenant_anchor(tenant_id, event_hash)
        result = verify_consent_proof(
            {
                "version": 1,
                "proof_type": "CONSENT_STATE_AT_TIME",
                "tenant_id": tenant_id,
                "consent_id": consent_id,
                "asserted_at": "2026-02-25T00:00:00Z",
                "asserted_state": "ACTIVE",
                "tenant_anchor": tenant_anchor,
                "lineage": {
                    "version": 1,
                    "tenant_id": tenant_id,
                    "consent_id": consent_id,
                    "algorithm": "SHA256",
                    "canonicalization": "sorted-json-no-whitespace",
                    "tenant_anchor": tenant_anchor,
                    "events": [
                        {
                            "action": "created",
                            "event_hash": event_hash,
                            "prev_event_hash": None,
                            "created_at": "2026-02-24T00:00:00Z",
                        }
                    ],
                },
                "included_events": [
                    {
                        "action": "created",
                        "event_hash": event_hash,
                        "created_at": "2026-02-24T00:00:00Z",
                    }
                ],
            }
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["derived_state"], "ACTIVE")

    def test_tenant_isolation_on_proof_creation(self) -> None:
        consent = self._create_active_consent()
        with self.assertRaises(HTTPException) as exc:
            create_consent_proof(
                consent_id=consent.id,
                payload=type("Payload", (), {"asserted_at": datetime.now(timezone.utc)})(),
                response=Response(),
                db=self.db,
                tenant=self.tenant_b,
            )
        self.assertEqual(exc.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
