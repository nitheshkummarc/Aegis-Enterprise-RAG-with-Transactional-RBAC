"""Celery worker for async document ingestion.

IMPORTANT: This module creates its OWN SQLAlchemy engine and session factory,
separate from FastAPI's request-scoped session. Celery runs in its own process;
sharing a session/connection pool across processes causes connection-pool
exhaustion or 'no application context' errors under load.

Ingestion flow (post-refactor):
1. Receive {document_id, object_key} from the queue.
2. Idempotency check: if chunks already exist for this document_id, skip.
3. Download PDF from Supabase Storage to a temp file (deleted in `finally`).
4. Extract text → chunk → embed → batch insert → mark ready.
5. On success, delete the raw PDF from storage (dead weight after chunking).
6. On persistent failure (corrupt PDF, extraction error), mark as 'failed'
   (dead-letter) rather than infinite-retrying.

Also defines cleanup_stuck_documents, a periodic (Celery Beat) task that
dead-letters Documents orphaned in status='processing' with no chunks —
see the bottom of this module.
"""

import logging
import os
import tempfile
import uuid

from celery import Celery
from celery.exceptions import Retry
from sqlalchemy import create_engine, select, func
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
    beat_schedule={
        # Run via: celery -A app.ingestion.worker.celery_app beat
        "cleanup-stuck-documents": {
            "task": "cleanup_stuck_documents",
            "schedule": 900.0,  # every 15 minutes
        },
    },
)


# ---------------------------------------------------------------------------
# Worker-scoped database session (NOT shared with FastAPI)
# ---------------------------------------------------------------------------

# Worker-local engine — created once per process, NOT per task.
# Creating a new engine per task leaks connection pools.
#
# pool_size/max_overflow only apply to QueuePool (Postgres). SQLite's
# default pool class doesn't accept them, so skip them for sqlite:// URLs —
# needed for the test suite, which points DATABASE_URL at SQLite.
_worker_engine_kwargs = {"pool_pre_ping": True}
if not settings.DATABASE_URL.startswith("sqlite"):
    _worker_engine_kwargs.update(pool_size=3, max_overflow=5)
_worker_engine = create_engine(settings.DATABASE_URL, **_worker_engine_kwargs)
_WorkerSessionFactory = sessionmaker(
    autocommit=False, autoflush=False, bind=_worker_engine
)


def _get_worker_session() -> Session:
    """Create a new database session from the worker-local engine.

    This intentionally does NOT import or reuse FastAPI's get_db().
    Uses a module-level engine shared across tasks in this process.
    """
    return _WorkerSessionFactory()


# ---------------------------------------------------------------------------
# Supabase Storage helpers
# ---------------------------------------------------------------------------

def _download_from_storage(object_key: str, dest_path: str) -> None:
    """Download a file from Supabase Storage to a local path.

    Uses the service key for authenticated access to private buckets.
    """
    from supabase import create_client

    supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    file_bytes = supabase.storage.from_("documents").download(object_key)
    with open(dest_path, "wb") as f:
        f.write(file_bytes)


def _delete_from_storage(object_key: str) -> None:
    """Delete the raw PDF from Supabase Storage after successful ingestion.

    The PDF is dead weight after chunking — chunks + embeddings are what
    we actually query. This frees storage costs.
    """
    try:
        from supabase import create_client

        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
        supabase.storage.from_("documents").remove([object_key])
        logger.info("Deleted storage object: %s", object_key)
    except Exception as e:
        # Best-effort deletion — don't fail the task over this
        logger.warning("Failed to delete storage object %s: %s", object_key, e)


# ---------------------------------------------------------------------------
# Ingestion task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    autoretry_for=(),  # Retries are triggered explicitly via self.retry() below,
                        # not Celery's blanket autoretry, so terminal failures
                        # (corrupt PDF, extraction errors) can still fail fast.
    name="ingest_document",
)
def ingest_document(self, document_id: str, object_key: str) -> dict:
    """Process an uploaded PDF: download → extract → chunk → embed → store.

    The task follows this pipeline:
    0. Idempotency check: skip if chunks already exist for this document_id
    1. Download PDF from Supabase Storage to a temp file
    2. PyMuPDF text extraction (fail-fast on corrupt PDF — no retries)
    3. Recursive chunking (500 chars, 50 overlap)
    4. OpenAI embedding (retry with exponential backoff on rate limit)
    5. Batch insert chunks into document_chunks with min_role_level from parent
    6. Update document status to 'ready'
    7. Delete the raw PDF from storage (dead weight after chunking)

    All chunk inserts and the status update happen in a single transaction.
    A worker crash mid-batch never leaves status='ready' with partial chunks.

    On persistent extraction failures (corrupt PDF, empty content), the
    document is marked as 'failed' (dead-lettered) — no infinite retries.
    """
    from app.ingestion.parser import extract_text_from_pdf
    from app.ingestion.chunker import chunk_text
    from app.ingestion.embedder import embed_texts
    from app.db.models import Document, DocumentChunk

    db = _get_worker_session()
    temp_path = None

    try:
        doc = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not doc:
            logger.error("Document %s not found in database", document_id)
            return {"status": "error", "detail": "Document not found"}

        # ------------------------------------------------------------------
        # Step 0: Idempotency — skip if chunks already exist
        # Prevents duplicate OpenAI embedding charges on queue redelivery.
        # ------------------------------------------------------------------
        existing_count = db.execute(
            select(func.count()).where(DocumentChunk.document_id == doc.id)
        ).scalar()

        if existing_count and existing_count > 0:
            logger.info(
                "Document %s: %d chunks already exist, "
                "skipping re-ingestion (idempotency check)",
                document_id, existing_count,
            )
            # Ensure status is correct
            if doc.status != "ready":
                doc.status = "ready"
                db.commit()
            return {
                "status": "skipped",
                "document_id": document_id,
                "detail": "Chunks already exist — idempotent skip",
            }

        # ------------------------------------------------------------------
        # Step 1: Download PDF from Supabase Storage to temp file
        # ------------------------------------------------------------------
        temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(temp_fd)

        try:
            _download_from_storage(object_key, temp_path)
        except Exception as e:
            logger.warning(
                "Storage download failed for document %s (attempt %d/%d): %s",
                document_id, self.request.retries + 1, self.max_retries + 1, e,
            )
            # Transient (network/timeout) — retry per max_retries/
            # default_retry_delay. self.retry() re-raises `e` once retries
            # are exhausted, and the outer handler marks the doc failed.
            raise self.retry(exc=e)

        # ------------------------------------------------------------------
        # Step 2: PDF extraction (fail-fast — corrupt PDF is not transient)
        # Dead-letter: mark as 'failed', do not retry.
        # ------------------------------------------------------------------
        try:
            text = extract_text_from_pdf(temp_path)
        except (RuntimeError, Exception) as e:
            logger.error(
                "PDF extraction failed for document %s: %s", document_id, e
            )
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": f"PDF extraction error: {e}"}

        if not text.strip():
            logger.warning("Document %s produced no text content", document_id)
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": "PDF produced no text content"}

        # ------------------------------------------------------------------
        # Step 3: Chunking
        # ------------------------------------------------------------------
        chunks = chunk_text(text, chunk_size=500, chunk_overlap=50)
        logger.info(
            "Document %s: extracted %d chunks", document_id, len(chunks)
        )

        # ------------------------------------------------------------------
        # Step 4: Embedding (retry with exponential backoff for rate limits)
        # ------------------------------------------------------------------
        try:
            embeddings = _embed_with_retry(self, chunks)
        except Exception as e:
            logger.error(
                "Embedding failed for document %s after retries: %s", document_id, e
            )
            doc.status = "failed"
            db.commit()
            return {"status": "failed", "detail": f"Embedding error: {e}"}

        # ------------------------------------------------------------------
        # Step 5+6: Batch insert chunks + update status in ONE transaction
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

        # ------------------------------------------------------------------
        # Step 7: Delete raw PDF from storage (dead weight after chunking)
        # ------------------------------------------------------------------
        _delete_from_storage(object_key)

        logger.info(
            "Document %s: ingestion complete — %d chunks stored with min_role_level=%d",
            document_id, len(chunks), doc.min_role_level,
        )
        return {
            "status": "ready",
            "document_id": document_id,
            "chunks_created": len(chunks),
        }

    except Retry:
        # A retry is already scheduled — leave status='processing' as-is.
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unexpected error processing document %s", document_id)
        # Try to mark as failed (dead-letter)
        try:
            doc_retry = (
                db.query(Document)
                .filter(Document.id == uuid.UUID(document_id))
                .first()
            )
            if doc_retry:
                doc_retry.status = "failed"
                db.commit()
        except Exception as inner_e:
            logger.warning("Failed to mark document %s as failed: %s", document_id, inner_e)
        raise
    finally:
        # Best-effort temp file cleanup. On Windows, a handle PyMuPDF held
        # after a failed parse can still be locking the file here — that
        # must not crash the task or mask the real error.
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as e:
                logger.warning("Failed to remove temp file %s: %s", temp_path, e)
        db.close()


def _embed_with_retry(task, chunks: list[str]) -> list[list[float]]:
    """Embed chunks with retry logic for provider rate limits.

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
                "Groq rate limit hit (attempt %d/%d), retrying in %ds...",
                attempt, max_attempts, delay,
            )
            import time
            time.sleep(delay)
            delay *= 2  # Exponential backoff
        except Exception:
            # Non-rate-limit errors fail immediately — no retry
            raise

    raise RuntimeError("Embedding failed after max retries")  # Should not reach here


# ---------------------------------------------------------------------------
# Periodic cleanup task
# ---------------------------------------------------------------------------

@celery_app.task(name="cleanup_stuck_documents")
def cleanup_stuck_documents() -> dict:
    """Dead-letter Documents stuck in status='processing' with no chunks.

    Covers rows orphaned before ingest_document ever runs (lost Celery
    message, worker killed before its first commit, etc). Runs on a
    schedule via Celery Beat — see beat_schedule above.
    """
    from datetime import datetime, timedelta, timezone
    from app.db.models import Document, DocumentChunk

    timeout_minutes = get_settings().STUCK_DOCUMENT_TIMEOUT_MINUTES
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    db = _get_worker_session()
    try:
        stuck_docs = (
            db.query(Document)
            .filter(Document.status == "processing", Document.updated_at < cutoff)
            .all()
        )

        cleaned_ids = []
        for doc in stuck_docs:
            chunk_count = db.execute(
                select(func.count()).where(DocumentChunk.document_id == doc.id)
            ).scalar()
            if chunk_count:
                # Chunks exist but status was never flipped — needs manual
                # review, not an auto dead-letter.
                continue
            doc.status = "failed"
            cleaned_ids.append(str(doc.id))

        db.commit()

        if cleaned_ids:
            logger.warning(
                "cleanup_stuck_documents: marked %d document(s) as 'failed' "
                "(stuck in 'processing' with no chunks for over %d minutes): %s",
                len(cleaned_ids), timeout_minutes, cleaned_ids,
            )

        return {"cleaned_count": len(cleaned_ids), "document_ids": cleaned_ids}
    finally:
        db.close()
