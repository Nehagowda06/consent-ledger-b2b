from fastapi import APIRouter, Body, HTTPException, Request

from core.json_safety import validate_strict_json_object
from core.lineage_verify import verify_consent_proof

router = APIRouter(prefix="/proofs", tags=["proofs"])

MAX_PROOF_VERIFY_BODY_BYTES = 262_144


@router.post("/verify")
async def verify_proof(
    request: Request,
    proof: dict = Body(...),
):
    raw = await request.body()
    if len(raw) > MAX_PROOF_VERIFY_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    validate_strict_json_object(raw)
    return verify_consent_proof(proof)
