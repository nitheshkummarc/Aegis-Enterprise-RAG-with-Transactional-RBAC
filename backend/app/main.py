"""FastAPI application entrypoint for ClearanceRAG."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.core.limiter import limiter

from app.auth.routes import router as auth_router
from app.documents.routes import router as documents_router
from app.retrieval.routes import router as retrieval_router

app = FastAPI(
    title="ClearanceRAG",
    description="Permission-aware RAG system with RBAC enforced at the database layer.",
    version="0.1.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: Origins are configurable via CORS_ORIGINS setting.
# Defaults to localhost:3000 for development.
from app.config import get_settings as _get_settings
_cors_origins = _get_settings().CORS_ORIGINS.split(",") if _get_settings().CORS_ORIGINS else ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Register routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(documents_router, prefix="/documents", tags=["documents"])
app.include_router(retrieval_router, prefix="/retrieval", tags=["retrieval"])


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
