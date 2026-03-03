import unittest
import uuid

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.audit import AuditEvent
from models.consent import Consent
from models.tenant import Tenant
from routers.consents import upsert_consent
from schemas.consent import ConsentUpsert


class UpsertConsentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-upsert")
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_create_update_noop(self) -> None:
        created = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-1", purpose="marketing_emails", status="ACTIVE"),
            db=self.db,
            tenant=self.tenant,
        )
        self.assertEqual(created.status.value, "ACTIVE")

        updated = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-1", purpose="marketing_emails", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        self.assertEqual(updated.status.value, "REVOKED")

        noop = upsert_consent(
            payload=ConsentUpsert(subject_id="subj-1", purpose="marketing_emails", status="REVOKED"),
            db=self.db,
            tenant=self.tenant,
        )
        self.assertEqual(noop.status.value, "REVOKED")

        consents = list(
            self.db.scalars(
                select(Consent).where(
                    Consent.tenant_id == self.tenant.id,
                    Consent.subject_id == "subj-1",
                    Consent.purpose == "marketing_emails",
                )
            ).all()
        )
        self.assertEqual(len(consents), 1)

        events = list(
            self.db.scalars(
                select(AuditEvent).where(AuditEvent.consent_id == created.id)
            ).all()
        )
        actions = [event.action for event in events]
        self.assertEqual(actions.count("consent.created"), 1)
        self.assertEqual(actions.count("consent.updated"), 1)
        self.assertEqual(actions.count("consent.noop"), 1)


if __name__ == "__main__":
    unittest.main()
