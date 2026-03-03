from fastapi import APIRouter, Body, HTTPException, Request

from core.json_safety import validate_strict_json_object
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
    validate_strict_json_object(raw)
    return verify_system_proof(proof)

