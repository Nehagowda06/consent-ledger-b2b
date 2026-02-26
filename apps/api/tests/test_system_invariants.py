import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.external_anchor import export_anchor_snapshot, verify_anchor_snapshot
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from models.consent_lineage import ConsentLineageEvent
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


class SystemInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-invariants")
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_lineage_length_monotonic_increase(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="inv", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        l1 = len(export_consent_lineage(consent.id, self.tenant.id, self.db)["events"])
        upsert_consent(
            payload=ConsentUpsert(subject_id="inv", purpose="mail", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        l2 = len(export_consent_lineage(consent.id, self.tenant.id, self.db)["events"])
        upsert_consent(
            payload=ConsentUpsert(subject_id="inv", purpose="mail", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        l3 = len(export_consent_lineage(consent.id, self.tenant.id, self.db)["events"])
        self.assertLess(l1, l2)
        self.assertLess(l2, l3)

    def test_event_hash_uniqueness_per_tenant(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="uniq", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="uniq", purpose="mail", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        rows = list(
            self.db.scalars(
                select(ConsentLineageEvent).where(ConsentLineageEvent.tenant_id == self.tenant.id)
            ).all()
        )
        hashes = [row.event_hash for row in rows]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertIsNotNone(consent.id)

    def test_tenant_anchor_stability_without_new_events(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="anchor", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        a1 = export_consent_lineage(consent.id, self.tenant.id, self.db)["tenant_anchor"]
        a2 = export_consent_lineage(consent.id, self.tenant.id, self.db)["tenant_anchor"]
        self.assertEqual(a1, a2)

    def test_proof_verification_implies_lineage_verification(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="proof", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        proof = build_consent_proof(consent.id, self.tenant.id, datetime.now(timezone.utc), self.db)
        proof_result = verify_consent_proof(proof)
        lineage_result = verify_exported_lineage(proof["lineage"])
        self.assertTrue(proof_result["verified"])
        self.assertTrue(lineage_result["verified"])

    def test_external_anchor_verification_implies_tenant_anchor_verification(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="ext", purpose="mail", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        snapshot = export_anchor_snapshot(self.db)
        self.assertTrue(verify_anchor_snapshot(snapshot)["verified"])
        lineage = export_consent_lineage(consent.id, self.tenant.id, self.db)
        self.assertTrue(verify_exported_lineage(lineage)["anchor_verified"])


if __name__ == "__main__":
    unittest.main()
