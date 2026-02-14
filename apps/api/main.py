from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "Consent Ledger API running"}
