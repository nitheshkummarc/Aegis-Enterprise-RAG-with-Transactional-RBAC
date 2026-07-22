"""FastAPI application entrypoint for ClearanceRAG."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.documents.routes import router as documents_router

app = FastAPI(
    title="ClearanceRAG",
    description="Permission-aware RAG system with RBAC enforced at the database layer.",
    version="0.1.0",
)

# CORS: Allow the Next.js frontend on localhost:3000.
# Added in Phase 1 per the Master Build Prompt to prevent silent
# failures when the frontend calls the backend in Phase 4.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(documents_router, prefix="/documents", tags=["documents"])


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
