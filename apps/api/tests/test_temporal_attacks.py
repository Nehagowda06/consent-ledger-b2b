import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.consent_proof import build_consent_proof
from core.db import Base
from core.lineage import compute_event_hash
from core.lineage_anchor import compute_tenant_anchor
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_consent_proof
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TemporalAttackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-time")
        self.db.add(self.tenant)
        self.db.commit()

        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="time-subj", purpose="time-purpose", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="time-subj", purpose="time-purpose", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="time-subj", purpose="time-purpose", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_asserted_at_exact_event_time_includes_event(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant.id, self.db)
        exact = _parse(artifact["events"][0]["created_at"])
        proof = build_consent_proof(self.consent.id, self.tenant.id, exact, self.db)
        self.assertEqual(len(proof["included_events"]), 1)
        self.assertEqual(proof["asserted_state"], "ACTIVE")

    def test_asserted_at_between_events_derives_prior_state(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant.id, self.db)
        t1 = _parse(artifact["events"][0]["created_at"])
        t2 = _parse(artifact["events"][1]["created_at"])
        between = t1 + (t2 - t1) / 2
        proof = build_consent_proof(self.consent.id, self.tenant.id, between, self.db)
        self.assertEqual(proof["asserted_state"], "ACTIVE")
        self.assertEqual(len(proof["included_events"]), 1)

    def test_asserted_at_before_first_event_fails(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant.id, self.db)
        before = _parse(artifact["events"][0]["created_at"]) - timedelta(seconds=1)
        with self.assertRaises(ValueError):
            build_consent_proof(self.consent.id, self.tenant.id, before, self.db)

    def test_asserted_at_after_revoke_before_reactivate_is_revoked(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant.id, self.db)
        revoke_t = _parse(artifact["events"][1]["created_at"])
        reactivate_t = _parse(artifact["events"][2]["created_at"])
        between = revoke_t + (reactivate_t - revoke_t) / 2
        proof = build_consent_proof(self.consent.id, self.tenant.id, between, self.db)
        result = verify_consent_proof(proof)
        self.assertTrue(result["verified"])
        self.assertEqual(result["derived_state"], "REVOKED")

    def test_asserted_at_far_future_fails(self) -> None:
        future = datetime.now(timezone.utc) + timedelta(days=36500)
        with self.assertRaises(ValueError):
            build_consent_proof(self.consent.id, self.tenant.id, future, self.db)

    def test_identical_timestamps_offline_proof_is_deterministic(self) -> None:
        tenant_id = str(uuid.uuid4())
        consent_id = str(uuid.uuid4())
        created_at = "2026-02-25T00:00:00Z"
        h1 = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "created", "payload": {}},
            None,
        )
        h2 = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "revoked", "payload": {}},
            h1,
        )
        anchor = compute_tenant_anchor(tenant_id, h2)
        proof = {
            "version": 1,
            "proof_type": "CONSENT_STATE_AT_TIME",
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "asserted_at": created_at,
            "asserted_state": "REVOKED",
            "tenant_anchor": anchor,
            "lineage": {
                "version": 1,
                "tenant_id": tenant_id,
                "consent_id": consent_id,
                "algorithm": "SHA256",
                "canonicalization": "sorted-json-no-whitespace",
                "tenant_anchor": anchor,
                "events": [
                    {"action": "created", "event_hash": h1, "prev_event_hash": None, "created_at": created_at},
                    {"action": "revoked", "event_hash": h2, "prev_event_hash": h1, "created_at": created_at},
                ],
            },
            "included_events": [
                {"action": "created", "event_hash": h1, "created_at": created_at},
                {"action": "revoked", "event_hash": h2, "created_at": created_at},
            ],
        }
        result = verify_consent_proof(proof)
        self.assertTrue(result["verified"])
        self.assertEqual(result["derived_state"], "REVOKED")


if __name__ == "__main__":
    unittest.main()
