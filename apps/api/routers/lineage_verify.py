import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.exceptions import RequestValidationError

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
    try:
        json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RequestValidationError(
            [{"loc": ("body",), "msg": "Invalid JSON payload", "type": "value_error.jsondecode"}]
        )
    return verify_exported_lineage(export)
