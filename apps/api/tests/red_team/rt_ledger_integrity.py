from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone

from core.lineage import compute_event_hash
from core.lineage_anchor import compute_tenant_anchor
from core.lineage_verify import verify_consent_proof, verify_exported_lineage
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert
from tests.red_team._helpers import make_memory_session


class RedTeamLedgerIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self.engine = make_memory_session()
        self.tenant = Tenant(
            id=uuid.UUID("00000000-0000-0000-0000-00000000aa01"),
            name="rt-ledger-tenant",
        )
        self.db.add(self.tenant)
        self.db.commit()
        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="rt-ledger-subj", purpose="analytics", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_rejects_forked_lineage_chain(self) -> None:
        tenant_id = str(self.tenant.id)
        consent_id = str(self.consent.id)
        e1 = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "created", "payload": {}},
            None,
        )
        fork_a = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "updated", "payload": {}},
            e1,
        )
        fork_b = compute_event_hash(
            {"tenant_id": tenant_id, "consent_id": consent_id, "action": "revoked", "payload": {}},
            e1,
        )
        export = {
            "version": 1,
            "tenant_id": tenant_id,
            "consent_id": consent_id,
            "algorithm": "SHA256",
            "canonicalization": "sorted-json-no-whitespace",
            "tenant_anchor": compute_tenant_anchor(tenant_id, fork_b),
            "events": [
                {"action": "created", "event_hash": e1, "prev_event_hash": None, "created_at": "2026-01-01T00:00:00Z"},
                {"action": "updated", "event_hash": fork_a, "prev_event_hash": e1, "created_at": "2026-01-01T00:00:01Z"},
                {"action": "revoked", "event_hash": fork_b, "prev_event_hash": e1, "created_at": "2026-01-01T00:00:02Z"},
            ],
        }
        result = verify_exported_lineage(export)
        self.assertFalse(result["verified"])
        self.assertIn("prev_event_hash", str(result["failure_reason"]))

    def test_rejects_partial_included_events(self) -> None:
        t = datetime.now(timezone.utc)
        upsert_consent(
            payload=ConsentUpsert(subject_id="rt-ledger-subj", purpose="analytics", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        proof = {
            "version": 1,
            "proof_type": "CONSENT_STATE_AT_TIME",
            "tenant_id": str(self.tenant.id),
            "consent_id": str(self.consent.id),
            "asserted_at": t.isoformat().replace("+00:00", "Z"),
            "asserted_state": "ACTIVE",
            "tenant_anchor": "deadbeef",
            "lineage": {
                "version": 1,
                "tenant_id": str(self.tenant.id),
                "consent_id": str(self.consent.id),
                "algorithm": "SHA256",
                "canonicalization": "sorted-json-no-whitespace",
                "tenant_anchor": "deadbeef",
                "events": [
                    {"action": "created", "event_hash": "a" * 64, "prev_event_hash": None, "created_at": "2026-01-01T00:00:00Z"},
                    {"action": "revoked", "event_hash": "b" * 64, "prev_event_hash": "a" * 64, "created_at": "2026-01-01T00:00:01Z"},
                ],
            },
            "included_events": [
                {"action": "created", "event_hash": "a" * 64, "created_at": "2026-01-01T00:00:00Z"},
            ],
        }
        result = verify_consent_proof(proof)
        self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
