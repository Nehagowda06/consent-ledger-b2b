from fastapi import FastAPI
from routers.health import router as health_router

app = FastAPI(title="Consent Ledger API")

app.include_router(health_router)

@app.get("/")
def root():
    return {"status": "Consent Ledger API running"}

from routers.consents import router as consents_router
app.include_router(consents_router)
