from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from uuid import UUID
from datetime import datetime, timezone

try:
    # Pydantic v2
    from pydantic import BaseModel, ConfigDict
    _PYDANTIC_V2 = True
except ImportError:
    # Pydantic v1
    from pydantic import BaseModel
    ConfigDict = None
    _PYDANTIC_V2 = False

from core.deps import get_db
from models.consent import Consent, ConsentStatus
from models.audit import AuditEvent
from schemas.consent import ConsentCreate, ConsentOut

router = APIRouter(prefix="/consents", tags=["consents"])


class AuditEventOut(BaseModel):
    consent_id: UUID
    action: str
    actor: str
    at: datetime

    if _PYDANTIC_V2:
        model_config = ConfigDict(from_attributes=True)
    else:
        class Config:
            orm_mode = True


@router.post("", response_model=ConsentOut)
def create_consent(payload: ConsentCreate, db: Session = Depends(get_db)):
    consent = Consent(subject_id=payload.subject_id, purpose=payload.purpose)
    db.add(consent)

    # flush so consent.id exists before creating audit row
    db.flush()

    audit = AuditEvent(
        consent_id=consent.id,
        action="CREATED",
        actor="system",
    )
    db.add(audit)

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

    if consent.status == ConsentStatus.REVOKED:
        raise HTTPException(status_code=409, detail="Consent already revoked")

    consent.status = ConsentStatus.REVOKED
    consent.revoked_at = datetime.now(timezone.utc)
    db.add(consent)

    audit = AuditEvent(
        consent_id=consent.id,
        action="REVOKED",
        actor="system",
    )
    db.add(audit)

    db.commit()
    db.refresh(consent)
    return consent


@router.get("/{consent_id}/audit", response_model=list[AuditEventOut])
def get_consent_audit(consent_id: UUID, db: Session = Depends(get_db)):
    consent = db.get(Consent, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="Consent not found")

    events = (
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.consent_id == consent_id)
            .order_by(AuditEvent.at.asc())
        ).all()
    )
    return events