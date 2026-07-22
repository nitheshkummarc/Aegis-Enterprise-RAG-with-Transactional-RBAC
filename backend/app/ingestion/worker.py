"""Celery worker for async document ingestion.

IMPORTANT: This module creates its OWN SQLAlchemy engine and session factory,
separate from FastAPI's request-scoped session. Celery runs in its own process;
sharing a session/connection pool across processes causes connection-pool
exhaustion or 'no application context' errors under load.
"""

import logging
import uuid

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

settings = get_settings()

celery_app = Celery(
    "clearancerag",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


# ---------------------------------------------------------------------------
# Worker-scoped database session (NOT shared with FastAPI)
# ---------------------------------------------------------------------------

def _get_worker_session() -> Session:
    """Create a new database session scoped to the worker process.

    This intentionally does NOT import or reuse FastAPI's get_db().
    Each call creates a fresh session from a worker-local engine.
    """
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    WorkerSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return WorkerSession()


# ---------------------------------------------------------------------------
# Ingestion task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(),  # We handle retries manually for OpenAI only
    name="ingest_document",
)
def ingest_document(self, document_id: str, file_path: str) -> dict:
    """Process an uploaded PDF: extract → chunk → embed → store.

    The task follows this pipeline:
    1. PyMuPDF text extraction (fail-fast on corrupt PDF — no retries)
    2. Recursive chunking (500 chars, 50 overlap)
    3. OpenAI embedding (retry with exponential backoff on rate limit)
    4. Batch insert chunks into document_chunks with min_role_level from parent
    5. Update document status to 'ready'

    All chunk inserts and the status update happen in a single transaction.
    A worker crash mid-batch never leaves status='ready' with partial chunks.
    """
    # Import here to avoid circular imports at module load time
    from app.ingestion.parser import extract_text_from_pdf
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embedder import embed_texts
    from app.db.models import Document, DocumentChunk

    db = _get_worker_session()

    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            logger.error(f"Document {document_id} not found in database")
            return {"status": "error", "detail": "Document not found"}

        # ------------------------------------------------------------------
        # Step 1: PDF extraction (fail-fast — corrupt PDF is not transient)
        # ------------------------------------------------------------------
        try:
            text = extract_text_from_pdf(file_path)
        except (RuntimeError, Exception) as e:
            logger.error(
                f"PDF extraction failed for document {document_id}: {e}"
            )
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": f"PDF extraction error: {e}"}

        if not text.strip():
            logger.warning(f"Document {document_id} produced no text content")
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": "PDF produced no text content"}

        # ------------------------------------------------------------------
        # Step 2: Chunking
        # ------------------------------------------------------------------
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        logger.info(
            f"Document {document_id}: extracted {len(chunks)} chunks"
        )

        # ------------------------------------------------------------------
        # Step 3: Embedding (retry with exponential backoff for rate limits)
        # ------------------------------------------------------------------
        try:
            embeddings = _embed_with_retry(self, chunks)
        except Exception as e:
            logger.error(
                f"Embedding failed for document {document_id} after retries: {e}"
            )
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": f"Embedding error: {e}"}

        # ------------------------------------------------------------------
        # Step 4+5: Batch insert chunks + update status in ONE transaction
        # ------------------------------------------------------------------
        for i, (chunk_text_content, embedding) in enumerate(
            zip(chunks, embeddings)
        ):
            chunk = DocumentChunk(
                document_id=doc.id,
                chunk_index=i,
                text_content=chunk_text_content,
                embedding=embedding,
                min_role_level=doc.min_role_level,  # Denormalized from parent
            )
            db.add(chunk)

        doc.status = "ready"
        db.commit()

        logger.info(
            f"Document {document_id}: ingestion complete — "
            f"{len(chunks)} chunks stored with min_role_level={doc.min_role_level}"
        )
        return {
            "status": "ready",
            "document_id": document_id,
            "chunks_created": len(chunks),
        }

    except Exception as e:
        db.rollback()
        logger.exception(f"Unexpected error processing document {document_id}")
        # Try to mark as failed
        try:
            doc_retry = (
                db.query(Document)
                .filter(Document.id == uuid.UUID(document_id))
                .first()
            )
            if doc_retry:
                doc_retry.status = "failed"
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()


def _embed_with_retry(task, chunks: list[str]) -> list[list[float]]:
    """Embed chunks with retry logic for OpenAI rate limits.

    Only retries on rate limit errors (429). Other errors fail immediately.
    Uses Celery's retry mechanism with exponential backoff (max 3 attempts).
    """
    import openai
    from app.ingestion.embedder import embed_texts

    attempt = 0
    max_attempts = 3
    delay = 5  # seconds, doubles each attempt

    while attempt < max_attempts:
        try:
            return embed_texts(chunks)
        except openai.RateLimitError as e:
            attempt += 1
            if attempt >= max_attempts:
                raise
            logger.warning(
                f"OpenAI rate limit hit (attempt {attempt}/{max_attempts}), "
                f"retrying in {delay}s..."
            )
            import time
            time.sleep(delay)
            delay *= 2  # Exponential backoff
        except Exception:
            # Non-rate-limit errors fail immediately — no retry
            raise

    raise RuntimeError("Embedding failed after max retries")  # Should not reach here
