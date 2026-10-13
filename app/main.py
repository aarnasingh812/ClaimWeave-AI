from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.auth import router as auth_router
from app.api.claims import router as claims_router
from app.api.workflows import router as workflow_router
from app.core.config import settings

app = FastAPI(title="ClaimWeave API", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                   allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                   allow_headers=["Content-Type", "Authorization"])
app.include_router(auth_router)
app.include_router(claims_router)
app.include_router(workflow_router)
from app.api.policy_sources import router as policy_source_router
app.include_router(policy_source_router)
from app.api.health import router as health_router
app.include_router(health_router)

@app.get("/health")
def health():
    return {"status": "ok"}
