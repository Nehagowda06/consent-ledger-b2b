import unittest
import uuid

from fastapi import HTTPException, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from core.lineage_export import export_consent_lineage
from core.lineage_verify import verify_exported_lineage
from core.lineage_anchor import compute_tenant_anchor
from models.tenant import Tenant
from routers.consents import get_consent_lineage_export, upsert_consent
from schemas.consent import ConsentUpsert


class LineageVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        self.tenant_a = Tenant(id=uuid.uuid4(), name="tenant-verifier-a")
        self.tenant_b = Tenant(id=uuid.uuid4(), name="tenant-verifier-b")
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

        self.consent = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-1", purpose="emails", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="subj-1", purpose="emails", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_a,
        )

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_exported_lineage_verifies_successfully(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        result = verify_exported_lineage(artifact)
        self.assertTrue(result["verified"])
        self.assertTrue(result["anchor_verified"])
        self.assertIsNone(result["failure_index"])
        self.assertIsNone(result["failure_reason"])

    def test_tampered_hash_fails_verification(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        artifact["events"][1]["event_hash"] = "f" * 64
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertEqual(result["failure_index"], 1)

    def test_removed_event_fails_verification(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        artifact["events"].pop(0)
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertIsNotNone(result["failure_reason"])

    def test_reordered_events_fail_verification(self) -> None:
        artifact = export_consent_lineage(self.consent.id, self.tenant_a.id, self.db)
        artifact["events"][0], artifact["events"][1] = artifact["events"][1], artifact["events"][0]
        result = verify_exported_lineage(artifact)
        self.assertFalse(result["verified"])
        self.assertIsNotNone(result["failure_reason"])

    def test_verifier_works_without_db_session(self) -> None:
        tenant_id = str(uuid.uuid4())
        result = verify_exported_lineage(
            {
                "version": 1,
                "tenant_id": tenant_id,
                "consent_id": str(uuid.uuid4()),
                "algorithm": "SHA256",
                "canonicalization": "sorted-json-no-whitespace",
                "tenant_anchor": compute_tenant_anchor(tenant_id, ""),
                "events": [],
            }
        )
        self.assertTrue(result["verified"])

    def test_verifier_rejects_malformed_schema(self) -> None:
        result = verify_exported_lineage({"version": 1})
        self.assertFalse(result["verified"])
        self.assertEqual(result["failure_index"], None)

    def test_export_endpoint_tenant_isolation_and_no_store(self) -> None:
        response = Response()
        artifact = get_consent_lineage_export(
            consent_id=self.consent.id,
            response=response,
            db=self.db,
            tenant=self.tenant_a,
        )
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(artifact["consent_id"], str(self.consent.id))
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
