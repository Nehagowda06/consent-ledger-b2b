from fastapi import FastAPI
from routers.health import router as health_router
from core.db import Base, engine
from models import consent, audit  # ensure models are imported so tables are registered

app = FastAPI(title="Consent Ledger API")
Base.metadata.create_all(bind=engine)

app.include_router(health_router)

@app.get("/")
def root():
    return {"status": "Consent Ledger API running"}

from routers.consents import router as consents_router
app.include_router(consents_router)
