from fastapi import APIRouter, Body, HTTPException, Request

from core.json_safety import validate_strict_json_object
from core.lineage_verify import verify_exported_lineage

router = APIRouter(prefix="/lineage", tags=["lineage"])

MAX_VERIFY_BODY_BYTES = 262_144


@router.post("/verify")
async def verify_lineage_export(
    request: Request,
    export: dict = Body(...),
):
    raw = await request.body()
    if len(raw) > MAX_VERIFY_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    validate_strict_json_object(raw)
    return verify_exported_lineage(export)
