import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.idempotency_key import IdempotencyKey


@dataclass
class IdempotencyReplay:
    response_json: dict[str, Any]
    status_code: int


def get_idempotency_key(request: Request | None) -> str | None:
    if request is None:
        return None
    value = request.headers.get("Idempotency-Key")
    if not value:
        return None
    key = value.strip()
    return key or None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)


def build_request_hash(method: str, path: str, body: dict[str, Any] | None = None) -> str:
    canonical_payload = _canonical_json(body or {})
    digest_input = f"{method.upper()}|{path}|{canonical_payload}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def check_idempotency(
    db: Session,
    tenant_id: uuid.UUID,
    key: str | None,
    request_hash: str | None,
) -> IdempotencyReplay | None:
    if not key or not request_hash:
        return None

    stored = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.key == key,
        )
    )
    if stored is None:
        return None

    if not hmac.compare_digest(stored.request_hash, request_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key reuse with different request",
        )

    return IdempotencyReplay(
        response_json=stored.response_json,
        status_code=stored.status_code,
    )


def store_idempotency_result(
    db: Session,
    tenant_id: uuid.UUID,
    key: str | None,
    request_hash: str | None,
    response_json: dict[str, Any],
    status_code: int,
) -> None:
    if not key or not request_hash:
        return

    db.add(
        IdempotencyKey(
            tenant_id=tenant_id,
            key=key,
            request_hash=request_hash,
            response_json=response_json,
            status_code=status_code,
        )
    )
