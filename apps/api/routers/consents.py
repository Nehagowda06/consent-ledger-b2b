from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from uuid import UUID
from datetime import datetime, timezone

from core.deps import get_db
from core.db import Base, engine
from models.consent import Consent, ConsentStatus
from schemas.consent import ConsentCreate, ConsentOut

router = APIRouter(prefix="/consents", tags=["consents"])

# Prototype: auto-create tables (later we'll switch to Alembic migrations)
Base.metadata.create_all(bind=engine)

@router.post("", response_model=ConsentOut)
def create_consent(payload: ConsentCreate, db: Session = Depends(get_db)):
    consent = Consent(subject_id=payload.subject_id, purpose=payload.purpose)
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent

@router.get("/{consent_id}", response_model=ConsentOut)
def get_consent(consent_id: UUID, db: Session = Depends(get_db)):
    consent = db.get(Consent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    return consent

@router.get("", response_model=list[ConsentOut])
def list_consents(subject_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Consent)
    if subject_id:
        stmt = stmt.where(Consent.subject_id == subject_id)
    return list(db.scalars(stmt).all())

@router.post("/{consent_id}/revoke", response_model=ConsentOut)
def revoke_consent(consent_id: UUID, db: Session = Depends(get_db)):
    consent = db.get(Consent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")
    consent.status = ConsentStatus.REVOKED
    consent.revoked_at = datetime.now(timezone.utc)
    db.add(consent)
    db.commit()
    db.refresh(consent)
    return consent
