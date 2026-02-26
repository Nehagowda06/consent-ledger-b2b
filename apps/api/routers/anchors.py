import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from core.external_anchor import verify_anchor_snapshot

router = APIRouter(prefix="/anchors", tags=["anchors"])

MAX_SNAPSHOT_VERIFY_BODY_BYTES = 262_144


@router.post("/verify")
async def verify_snapshot(
    request: Request,
    snapshot: dict = Body(...),
):
    raw = await request.body()
    if len(raw) > MAX_SNAPSHOT_VERIFY_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RequestValidationError(
            [{"loc": ("body",), "msg": "Invalid JSON payload", "type": "value_error.jsondecode"}]
        )
    return verify_anchor_snapshot(snapshot)
