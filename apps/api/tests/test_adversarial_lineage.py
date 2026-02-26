import copy
import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.external_anchor import export_anchor_snapshot, verify_anchor_snapshot
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


class AdversarialLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-lineage-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-lineage-b")
        self.db.add_all([self.tenant_a, self.tenant_b])
        self.db.commit()
        self.consent_a = upsert_consent(
            payload=ConsentUpsert(subject_id="sa", purpose="pa", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="sa", purpose="pa", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_a,
        )
        self.consent_b = upsert_consent(
            payload=ConsentUpsert(subject_id="sb", purpose="pb", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_b,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_single_byte_hash_and_prev_hash_tampering_detected(self) -> None:
        artifact = export_consent_lineage(self.consent_a.id, self.tenant_a.id, self.db)
        tampered_hash = copy.deepcopy(artifact)
        original_hash = tampered_hash["events"][0]["event_hash"]
        replacement = "f" if original_hash[0] != "f" else "e"
        tampered_hash["events"][0]["event_hash"] = replacement + original_hash[1:]
        result_hash = verify_exported_lineage(tampered_hash)
        self.assertFalse(result_hash["verified"])
        self.assertEqual(result_hash["failure_index"], 0)

        tampered_prev = copy.deepcopy(artifact)
        tampered_prev["events"][1]["prev_event_hash"] = "0" * 64
        result_prev = verify_exported_lineage(tampered_prev)
        self.assertFalse(result_prev["verified"])
        self.assertEqual(result_prev["failure_index"], 1)

    def test_tenant_anchor_and_external_digest_tampering_detected(self) -> None:
        artifact = export_consent_lineage(self.consent_a.id, self.tenant_a.id, self.db)
        artifact["tenant_anchor"] = "0" * 64
        anchor_result = verify_exported_lineage(artifact)
        self.assertFalse(anchor_result["verified"])
        self.assertFalse(anchor_result["anchor_verified"])

        snapshot = export_anchor_snapshot(self.db)
        snapshot["digest"] = "f" * 64
        digest_result = verify_anchor_snapshot(snapshot)
        self.assertFalse(digest_result["verified"])

    def test_remove_duplicate_reorder_events_fail(self) -> None:
        artifact = export_consent_lineage(self.consent_a.id, self.tenant_a.id, self.db)

        removed = copy.deepcopy(artifact)
        removed["events"].pop(0)
        self.assertFalse(verify_exported_lineage(removed)["verified"])

        duplicated = copy.deepcopy(artifact)
        duplicated["events"].insert(1, dict(duplicated["events"][0]))
        self.assertFalse(verify_exported_lineage(duplicated)["verified"])

        reordered = copy.deepcopy(artifact)
        reordered["events"] = list(reversed(reordered["events"]))
        self.assertFalse(verify_exported_lineage(reordered)["verified"])

    def test_cross_tenant_and_cross_consent_lineage_reuse_fails(self) -> None:
        artifact_a = export_consent_lineage(self.consent_a.id, self.tenant_a.id, self.db)
        artifact_b = export_consent_lineage(self.consent_b.id, self.tenant_b.id, self.db)

        mixed = copy.deepcopy(artifact_a)
        mixed["events"] = artifact_a["events"][:1] + artifact_b["events"][:1]
        self.assertFalse(verify_exported_lineage(mixed)["verified"])

        reused = copy.deepcopy(artifact_a)
        reused["consent_id"] = str(self.consent_b.id)
        self.assertFalse(verify_exported_lineage(reused)["verified"])

    def test_malformed_lineage_and_proof_do_not_crash(self) -> None:
        malformed = {"version": 1, "events": "not-a-list"}
        result = verify_exported_lineage(malformed)
        self.assertFalse(result["verified"])
        self.assertIn("missing keys", result["failure_reason"])

        proof = build_consent_proof(
            consent_id=self.consent_a.id,
            tenant_id=self.tenant_a.id,
            asserted_at=datetime.now(timezone.utc),
            db=self.db,
        )
        proof["included_events"][0] = "bad-event"
        proof_result = verify_consent_proof(proof)
        self.assertFalse(proof_result["verified"])
        self.assertIn("included event", proof_result["failure_reason"])


if __name__ == "__main__":
    unittest.main()
