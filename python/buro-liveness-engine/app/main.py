from fastapi import FastAPI
from app.routes.liveness_routes import router as liveness_router

app = FastAPI(title="Liveness Engine", version="0.1.0")

app.include_router(liveness_router, prefix="/api/liveness", tags=["Liveness"])

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "liveness-engine"
    }