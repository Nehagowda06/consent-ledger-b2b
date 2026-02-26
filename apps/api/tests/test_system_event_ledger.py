import unittest
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.db import Base
from models.system_event import SystemEvent, compute_event_hash, compute_payload_hash
from models.tenant import Tenant


class SystemEventLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()
        self.tenant = Tenant(id=uuid.uuid4(), name="tenant-ledger")
        self.db.add(self.tenant)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _append_event(
        self,
        event_type: str,
        payload: dict,
        prev_hash: str | None,
    ) -> SystemEvent:
        created_at = datetime.now(timezone.utc)
        payload_hash = compute_payload_hash(payload)
        event_hash = compute_event_hash(
            tenant_id=str(self.tenant.id),
            event_type=event_type,
            resource_type="consent",
            resource_id="resource-1",
            payload_hash=payload_hash,
            prev_event_hash=prev_hash,
            created_at=created_at,
        )
        event = SystemEvent(
            tenant_id=self.tenant.id,
            event_type=event_type,
            resource_type="consent",
            resource_id="resource-1",
            payload_hash=payload_hash,
            prev_event_hash=prev_hash,
            event_hash=event_hash,
            created_at=created_at,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def test_event_insertion(self) -> None:
        event = self._append_event("consent.created", {"a": 1}, None)
        fetched = self.db.scalar(select(SystemEvent).where(SystemEvent.id == event.id))
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.event_type, "consent.created")
        self.assertEqual(len(fetched.payload_hash), 64)
        self.assertEqual(len(fetched.event_hash), 64)

    def test_chain_correctness(self) -> None:
        e1 = self._append_event("consent.created", {"s": "ACTIVE"}, None)
        e2 = self._append_event("consent.updated", {"s": "REVOKED"}, e1.event_hash)
        e3 = self._append_event("consent.noop", {"s": "REVOKED"}, e2.event_hash)
        self.assertEqual(e2.prev_event_hash, e1.event_hash)
        self.assertEqual(e3.prev_event_hash, e2.event_hash)

        prev = None
        for row in [e1, e2, e3]:
            expected = compute_event_hash(
                tenant_id=str(row.tenant_id) if row.tenant_id else None,
                event_type=row.event_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                payload_hash=row.payload_hash,
                prev_event_hash=prev,
                created_at=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at,
            )
            self.assertEqual(row.event_hash, expected)
            prev = row.event_hash

    def test_tamper_detection(self) -> None:
        e1 = self._append_event("consent.created", {"s": "ACTIVE"}, None)
        e2 = self._append_event("consent.updated", {"s": "REVOKED"}, e1.event_hash)
        self.db.execute(
            text("UPDATE system_event_ledger SET payload_hash = :h WHERE id = :id"),
            {"h": "0" * 64, "id": str(e2.id)},
        )
        self.db.commit()

        rows = list(
            self.db.scalars(
                select(SystemEvent).order_by(SystemEvent.created_at.asc(), SystemEvent.id.asc())
            ).all()
        )
        prev = None
        mismatch_found = False
        for row in rows:
            expected = compute_event_hash(
                tenant_id=str(row.tenant_id) if row.tenant_id else None,
                event_type=row.event_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                payload_hash=row.payload_hash,
                prev_event_hash=prev,
                created_at=row.created_at.replace(tzinfo=timezone.utc) if row.created_at.tzinfo is None else row.created_at,
            )
            if expected != row.event_hash:
                mismatch_found = True
                break
            prev = row.event_hash
        self.assertTrue(mismatch_found)


if __name__ == "__main__":
    unittest.main()
