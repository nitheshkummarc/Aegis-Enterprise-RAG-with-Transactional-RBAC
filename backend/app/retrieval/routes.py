"""Query route: embed → permission-filtered search → generate → SSE stream.

SSE payload format (from the Master Build Prompt):
    data: {"type": "token", "text": "partial answer chunk"}
    data: {"type": "error", "detail": "human-readable failure reason"}
    data: {"type": "done", "sources": [{"document_id": "...", "title": "...", "chunk_id": "..."}]}

The done event is ALWAYS the final event. Sources reflects exactly what the
permission-filtered search returned: empty means no permitted chunks (an
RBAC refusal), never a generation failure. A mid-stream LLM error emits an
"error" event first, then a done event with the real (permitted) sources —
this keeps generation failures distinguishable from access refusals. The
frontend's SourcesDropdown reads only from the final done event.
"""

import json
import logging
from contextlib import contextmanager

import openai

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.exceptions import ConfigurationError
from app.core.limiter import limiter
from app.db.models import User, ROLE_LEVEL_MAP
from app.db.session import get_db
from app.ingestion.embedder import embed_query
from app.retrieval.prompt import build_prompt
from app.retrieval.search import permission_filtered_search
from app.core.observability import get_client as get_langfuse_client
from app.retrieval.generate import generate_streaming, active_model_name

logger = logging.getLogger(__name__)

router = APIRouter()


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(max_length=2000)


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data event."""
    return f"data: {json.dumps(data)}\n\n"


def _start_query_trace(user: User, question: str):
    """Open the root Langfuse observation for a query, or return None.

    Uses the non-context-manager API because the SSE generator runs after this
    handler returns, possibly on another thread; the span is ended there.
    propagate_attributes applies user and role to spans created inside its
    block.
    """
    client = get_langfuse_client()
    if client is None:
        return None

    from langfuse import propagate_attributes

    with propagate_attributes(
        user_id=str(user.email),
        metadata={"role": user.role.value},
    ):
        return client.start_observation(
            name="rag-query",
            as_type="span",
            input=question,
        )


@contextmanager
def _retrieval_span(root, user: User):
    """Record the permission-filtered search as a retriever observation.

    Instrumented manually because a pgvector query is not a LangChain
    operation. Records the role and resolved role level used by the filter.
    """
    if root is None:
        yield None
        return

    span = root.start_observation(
        name="1. Permission-Filtered Retrieval",
        as_type="retriever",
        metadata={
            "user_role": user.role.value,
            "user_role_level": ROLE_LEVEL_MAP.get(user.role, 0),
        },
    )
    try:
        yield span
    finally:
        span.end()


@contextmanager
def _generation_span(root, prompt: str):
    """Make the generation the current observation while the model streams.

    Entered as the current OpenTelemetry context so the Langfuse LangChain
    callback nests its generation observation underneath. Entered and exited
    within the SSE generator so the context stays on one thread.
    """
    if root is None:
        yield None
        return

    with root.start_as_current_observation(
        name="2. LLM Generation",
        as_type="span",
        input=prompt,
    ) as span:
        yield span


@router.post("/query")
@limiter.limit("20/minute")
async def query(
    request: Request,
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Embed user query → permission-filtered search → LLM generation → SSE stream.

    Rate-limited like the other cost-sensitive routes (auth, upload-url):
    each call spends one embedding request and one generation request.
    """
    question = body.question

    # Root observation for this query. None when Langfuse is unconfigured;
    # every span helper below treats that as "tracing off".
    root_span = _start_query_trace(current_user, question)

    # ------------------------------------------------------------------
    # Step 1: Embed the user's question
    # ------------------------------------------------------------------
    try:
        query_embedding = embed_query(question)
    except openai.APIError as e:
        # Provider errors are transient and retryable. ConfigurationError is
        # not caught here, so misconfiguration surfaces rather than appearing
        # as a temporary failure.
        logger.error("Embedding request failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Failed to generate query embedding. Please try again.",
        )

    # ------------------------------------------------------------------
    # Step 2: Permission-filtered retrieval
    # ------------------------------------------------------------------
    with _retrieval_span(root_span, current_user) as retrieval_span:
        chunks = permission_filtered_search(
            db=db,
            query_embedding=query_embedding,
            user_role=current_user.role,
            limit=3,
        )
        if retrieval_span:
            retrieval_span.update(
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
        full_response = ""
        usage = {}

        try:
            with _generation_span(root_span, prompt) as generation_span:
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
                except ConfigurationError:
                    # Misconfiguration is not retryable; surface it rather
                    # than reporting a transient generation failure.
                    raise
                except Exception as e:
                    logger.error("Generation error: %s", e)
                    # sources was computed before generation started, so it's still
                    # the real, permission-checked result — send it, not [].
                    yield _sse_event({
                        "type": "error",
                        "detail": "Generation failed. Please try again.",
                    })
                    yield _sse_event({
                        "type": "done",
                        "sources": sources,
                    })

                if generation_span:
                    generation_span.update(
                        output=full_response,
                        metadata={
                            "model": active_model_name(),
                            "token_usage": usage,
                        },
                    )
        finally:
            # The root span outlives the handler, so the generator closes it.
            # No explicit flush: the client batches in the background and
            # flushes on process exit.
            if root_span is not None:
                root_span.update(output=full_response)
                root_span.end()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
