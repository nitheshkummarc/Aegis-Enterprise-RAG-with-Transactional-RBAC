"""Text generation via LangChain ChatGroq, with streaming support.

The chat model is selected by GROQ_MODEL and resolved once per process.

This layer is authorization-blind: it receives a finished prompt string and
returns text, with no database session, user, role, or retriever. Access
control is enforced entirely by the SQL filter in app.retrieval.search, so
LangChain retrieval constructs must not be introduced here.

The prompt arrives pre-rendered from app.retrieval.prompt.build_prompt and is
passed through unchanged. It is not wrapped in a ChatPromptTemplate, which
would re-parse the ``{...}`` placeholders that build_prompt substitutes.
"""

from typing import Any, Generator, Iterable

from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.core.exceptions import ConfigurationError
from app.core.observability import tracing_callbacks

# Excludes reasoning traces from the response. Reasoning-capable models would
# otherwise stream them into the token output.
REASONING_FORMAT = "hidden"

# Deterministic output, so evaluation runs are reproducible.
TEMPERATURE = 0.0


def active_model_name() -> str:
    """Return the chat model identifier this process is configured to use."""
    return _require_setting("GROQ_MODEL")


def _require_setting(name: str) -> str:
    """Return a required non-empty setting, or raise ConfigurationError."""
    value = (getattr(get_settings(), name, "") or "").strip()
    if not value:
        raise ConfigurationError(
            f"{name} is not set. Groq generation cannot start without it. "
            f"Set {name} in backend/.env (see .env.example)."
        )
    return value


def build_llm():
    """Construct the ChatGroq client for the configured model."""
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=active_model_name(),
        api_key=_require_setting("GROQ_API_KEY"),
        temperature=TEMPERATURE,
        reasoning_format=REASONING_FORMAT,
        streaming=True,
        callbacks=tracing_callbacks(),
    )


def _usage_from_chunk(chunk: Any) -> dict[str, int] | None:
    """Convert a chunk's usage metadata to the SSE contract's key names.

    Returns None when the chunk carries no usage data. Groq reports usage
    only on the final chunk, and may omit it entirely.
    """
    usage = getattr(chunk, "usage_metadata", None)
    if not usage:
        return None
    return {
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _stream_tokens(chunks: Iterable[Any]) -> Generator[dict[str, Any], None, None]:
    """Accumulate a LangChain chunk stream into SSE token and done events.

    Reads chunk.text rather than chunk.content so that only textual payload is
    emitted under either LangChain content format; non-text blocks such as
    reasoning are excluded.
    """
    full_response = ""
    usage: dict[str, int] | None = None

    for chunk in chunks:
        chunk_usage = _usage_from_chunk(chunk)
        if chunk_usage is not None:
            usage = chunk_usage

        text = chunk.text
        if text:
            full_response += text
            yield {"type": "token", "text": text}

    yield {
        "type": "done",
        "full_response": full_response,
        "usage": usage or {},
        "model": active_model_name(),
    }


def generate_streaming(system_prompt: str) -> Generator[dict[str, Any], None, None]:
    """Stream a completion from Groq.

    Yields dicts with:
        {"type": "token", "text": "partial chunk"}
        {"type": "done", "full_response": str, "usage": {...}, "model": str}

    The done event is always last. This shape is a fixed contract — the SSE
    route and the eval harness both depend on it.

    Args:
        system_prompt: The full prompt including context and question, already
            rendered by build_prompt. Sent as a single HumanMessage; the
            prompt's instructions are authored as user content.

    Yields:
        Token events during streaming, then a final done event with usage.
    """
    llm = build_llm()
    yield from _stream_tokens(llm.stream([HumanMessage(content=system_prompt)]))
