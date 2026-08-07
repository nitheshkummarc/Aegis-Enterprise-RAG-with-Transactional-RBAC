"""Query route: embed → permission-filtered search → generate → SSE stream.

SSE payload format (from the Master Build Prompt):
    data: {"type": "token", "text": "partial answer chunk"}
    data: {"type": "done", "sources": [{"document_id": "...", "title": "...", "chunk_id": "..."}]}

The done event is ALWAYS the final event. Sources is empty if the query was
refused (no permitted chunks found). The frontend's SourcesDropdown reads
only from this final event.
"""

import json
import logging

import openai

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import User, ROLE_LEVEL_MAP
from app.db.session import get_db
from app.retrieval.prompt import build_prompt
from app.retrieval.search import permission_filtered_search
from app.retrieval.generate import generate_streaming, GENERATION_MODEL

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(max_length=2000)


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data event."""
    return f"data: {json.dumps(data)}\n\n"


def _try_langfuse_trace(user: User, question: str):
    """Attempt to create a Langfuse trace. Returns (trace, enabled) tuple.

    If Langfuse keys are not configured, returns (None, False) gracefully
    so the query still works without observability.
    """
    settings = get_settings()
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return None, False

    try:
        from langfuse import Langfuse

        langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        trace = langfuse.trace(
            name="rag-query",
            user_id=str(user.email),
            metadata={"role": user.role.value},
            input=question,
        )
        return trace, True
    except Exception as e:
        logger.warning("Langfuse initialization failed: %s", e)
        return None, False


@router.post("/query")
async def query(
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Embed user query → permission-filtered search → LLM generation → SSE stream."""
    settings = get_settings()
    question = body.question

    # Initialize Langfuse trace (graceful fallback if not configured)
    trace, langfuse_enabled = _try_langfuse_trace(current_user, question)

    # ------------------------------------------------------------------
    # Step 1: Embed the user's question
    # ------------------------------------------------------------------
    try:
        client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        embed_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=question,
        )
        query_embedding = embed_response.data[0].embedding
    except openai.APIError as e:
        logger.error("OpenAI embedding failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Failed to generate query embedding. Please try again.",
        )

    # ------------------------------------------------------------------
    # Step 2: Permission-filtered retrieval
    # ------------------------------------------------------------------
    retrieval_span = None
    if langfuse_enabled and trace:
        retrieval_span = trace.span(
            name="1. Permission-Filtered Retrieval",
            metadata={
                "user_role": current_user.role.value,
                "user_role_level": ROLE_LEVEL_MAP.get(current_user.role, 0),
            },
        )

    chunks = permission_filtered_search(
        db=db,
        query_embedding=query_embedding,
        user_role=current_user.role,
        limit=3,
    )

    if retrieval_span:
        retrieval_span.end(
            output={"chunk_count": len(chunks)},
            metadata={"chunks_returned": len(chunks)},
        )

    # Build sources list for the done event
    sources = [
        {
            "document_id": c["document_id"],
            "title": c["title"],
            "chunk_id": c["chunk_id"],
        }
        for c in chunks
    ]

    # ------------------------------------------------------------------
    # Step 3: LLM Generation (stream via SSE)
    # ------------------------------------------------------------------
    if not chunks:
        # No permitted chunks — the LLM should refuse, but we also make
        # sure by providing empty context
        context = ""
    else:
        context = "\n\n---\n\n".join(c["text_content"] for c in chunks)

    prompt = build_prompt(context=context, question=question)

    def event_stream():
        generation_span = None
        if langfuse_enabled and trace:
            generation_span = trace.span(
                name="2. LLM Generation",
                metadata={"model": GENERATION_MODEL},
                input=prompt,
            )

        full_response = ""
        usage = {}

        try:
            for event in generate_streaming(prompt):
                if event["type"] == "token":
                    full_response += event["text"]
                    yield _sse_event({"type": "token", "text": event["text"]})
                elif event["type"] == "done":
                    usage = event.get("usage", {})
                    # Send sources ONLY in the done event, never in token events
                    yield _sse_event({
                        "type": "done",
                        "sources": sources,
                    })
        except Exception as e:
            logger.error(f"Generation error: {e}")
            yield _sse_event({
                "type": "done",
                "sources": [],
            })

        if generation_span:
            generation_span.end(
                output=full_response,
                metadata={
                    "model": GENERATION_MODEL,
                    "token_usage": usage,
                },
            )

        # Flush Langfuse
        if langfuse_enabled and trace:
            trace.update(output=full_response)
            try:
                from langfuse import Langfuse
                lf = Langfuse(
                    public_key=settings.LANGFUSE_PUBLIC_KEY,
                    secret_key=settings.LANGFUSE_SECRET_KEY,
                    host=settings.LANGFUSE_HOST,
                )
                lf.flush()
            except Exception:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
