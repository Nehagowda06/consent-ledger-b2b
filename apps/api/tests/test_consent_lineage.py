import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.consent import Consent
from models.consent_lineage import ConsentLineageEvent
from models.tenant import Tenant
from routers.consents import create_consent, get_consent_lineage, revoke_consent, upsert_consent
from schemas.consent import ConsentCreate, ConsentUpsert


class ConsentLineageTests(unittest.TestCase):
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
        self.db.add(self.tenant_a)
        self.db.add(self.tenant_b)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_lineage_created_on_create(self) -> None:
        consent = create_consent(
            payload=ConsentCreate(subject_id="user-100", purpose="marketing"),
            db=self.db,
            tenant=self.tenant_a,
        )
        lineage = get_consent_lineage(consent_id=consent.id, db=self.db, tenant=self.tenant_a)
        self.assertTrue(lineage["verified"])
        self.assertEqual(len(lineage["events"]), 1)
        self.assertEqual(lineage["events"][0]["action"], "created")

    def test_lineage_chained_on_update(self) -> None:
        consent = upsert_consent(
            payload=ConsentUpsert(subject_id="user-200", purpose="emails", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant_a,
        )
        upsert_consent(
            payload=ConsentUpsert(subject_id="user-200", purpose="emails", status="REVOKED"),
            db=self.db,
            tenant=self.tenant_a,
        )

        lineage = get_consent_lineage(consent_id=consent.id, db=self.db, tenant=self.tenant_a)
        self.assertTrue(lineage["verified"])
        self.assertEqual(len(lineage["events"]), 2)
        first, second = lineage["events"]
        self.assertEqual(first["action"], "created")
        self.assertEqual(second["action"], "updated")
        self.assertEqual(second["prev_event_hash"], first["event_hash"])

    def test_lineage_chained_on_revoke(self) -> None:
        consent = create_consent(
            payload=ConsentCreate(subject_id="user-300", purpose="ads"),
            db=self.db,
            tenant=self.tenant_a,
        )
        revoke_consent(consent_id=consent.id, db=self.db, tenant=self.tenant_a)

        lineage = get_consent_lineage(consent_id=consent.id, db=self.db, tenant=self.tenant_a)
        self.assertTrue(lineage["verified"])
        self.assertEqual(len(lineage["events"]), 2)
        self.assertEqual(lineage["events"][1]["action"], "revoked")

    def test_tamper_detected(self) -> None:
        consent = create_consent(
            payload=ConsentCreate(subject_id="user-400", purpose="analytics"),
            db=self.db,
            tenant=self.tenant_a,
        )
        event = self.db.scalar(
            select(ConsentLineageEvent).where(
                ConsentLineageEvent.tenant_id == self.tenant_a.id,
                ConsentLineageEvent.consent_id == consent.id,
            )
        )
        event.event_hash = "0" * 64
        self.db.add(event)
        self.db.commit()

        lineage = get_consent_lineage(consent_id=consent.id, db=self.db, tenant=self.tenant_a)
        self.assertFalse(lineage["verified"])

    def test_tenant_isolation(self) -> None:
        consent = create_consent(
            payload=ConsentCreate(subject_id="user-500", purpose="product_updates"),
            db=self.db,
            tenant=self.tenant_a,
        )
        with self.assertRaises(HTTPException) as exc:
            get_consent_lineage(consent_id=consent.id, db=self.db, tenant=self.tenant_b)
        self.assertEqual(exc.exception.status_code, 404)

    def test_lineage_failure_rolls_back_consent_write(self) -> None:
        with patch("routers.consents.add_lineage_event", side_effect=RuntimeError("lineage failed")):
            with self.assertRaises(RuntimeError):
                create_consent(
                    payload=ConsentCreate(subject_id="user-600", purpose="security"),
                    db=self.db,
                    tenant=self.tenant_a,
                )
        persisted = self.db.scalar(
            select(Consent).where(
                Consent.tenant_id == self.tenant_a.id,
                Consent.subject_id == "user-600",
                Consent.purpose == "security",
            )
        )
        self.assertIsNone(persisted)


if __name__ == "__main__":
    unittest.main()
