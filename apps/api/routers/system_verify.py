import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from core.system_proof import verify_system_proof

router = APIRouter(tags=["system"])

MAX_SYSTEM_VERIFY_BODY_BYTES = 262_144


@router.post("/system/verify")
async def verify_system_proof_endpoint(
    request: Request,
    proof: dict = Body(...),
):
    raw = await request.body()
    if len(raw) > MAX_SYSTEM_VERIFY_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RequestValidationError(
            [{"loc": ("body",), "msg": "Invalid JSON payload", "type": "value_error.jsondecode"}]
        )
    return verify_system_proof(proof)

