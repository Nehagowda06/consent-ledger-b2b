from fastapi import APIRouter
from core.config import APP_NAME, APP_VERSION
from sqlalchemy import text
from core.db import SessionLocal

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    return {"status": "ok"}

@router.get("/version")
def version():
    return {"name": APP_NAME, "version": APP_VERSION}

@router.get("/db")
def db_check():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"db": "ok"}
