from fastapi import APIRouter
from core.config import APP_NAME, APP_VERSION

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/version")
def version():
    return {"name": APP_NAME, "version": APP_VERSION}
