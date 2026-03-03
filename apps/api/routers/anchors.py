from fastapi import APIRouter, Body, HTTPException, Request

from core.external_anchor import verify_anchor_snapshot
from core.json_safety import validate_strict_json_object

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
    validate_strict_json_object(raw)
    return verify_anchor_snapshot(snapshot)
