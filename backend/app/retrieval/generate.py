"""Groq generation via LangChain, with streaming support.

The model is selected by ``GROQ_MODEL`` and resolved once per process. There
is deliberately no provider toggle and no OpenAI branch. Embeddings run on
Groq too (see app.ingestion.embedder), so the project needs exactly one
provider credential, GROQ_API_KEY.

Authorization note
------------------
This layer is, and must remain, authorization-blind. It receives a finished
prompt string and returns text. It has no DB session, no ``User``, no role,
and no retriever. Every access decision has already been made by
``permission_filtered_search``'s SQL ``WHERE dc.min_role_level <=
:user_role_level`` before the prompt string exists. Do not introduce
``create_retrieval_chain`` or a filtered ``VectorStore`` retriever here — that
would move the authorization boundary out of the database and into a
framework kwarg.

Prompt note
-----------
The prompt arrives pre-rendered from ``app.retrieval.prompt.build_prompt``
and is passed through untouched. It is deliberately NOT wrapped in a
``ChatPromptTemplate``: that class re-parses ``{...}`` placeholders, which
would reintroduce the injection bug ``build_prompt``'s single-pass regex
substitution exists to prevent.
"""

from typing import Any, Generator, Iterable

from langchain_core.messages import HumanMessage

from app.config import get_settings
from app.core.exceptions import ConfigurationError
from app.core.observability import tracing_callbacks

# Groq streams reasoning traces for reasoning-capable models (gpt-oss-120b
# among them). "hidden" keeps them out of the response entirely. This is a
# correctness requirement, not a preference: leaked reasoning text lands in
# the SSE token stream, is accumulated into full_response, and corrupts the
# eval harness's exact-substring check for the refusal string.
REASONING_FORMAT = "hidden"

# Deterministic output. The eval harness scores an exact refusal string, so
# sampling variance is measurement noise here.
TEMPERATURE = 0.0


def active_model_name() -> str:
    """The Groq model this process is serving.

    A function rather than a module constant so the value reported in traces
    and in the SSE done event always reflects configuration instead of a
    hardcoded literal that can drift from what actually ran.
    """
    return _require_setting("GROQ_MODEL")


def _require_setting(name: str) -> str:
    """Read a required non-empty setting, or fail loudly.

    Misconfiguration is not recoverable at request time and must not be
    degraded into a generic 502 — an operator needs to see which knob is
    unset, not "generation failed, please try again".
    """
    value = (getattr(get_settings(), name, "") or "").strip()
    if not value:
        raise ConfigurationError(
            f"{name} is not set. Groq generation cannot start without it. "
            f"Set {name} in backend/.env (see .env.example)."
        )
    return value


def build_llm():
    """Construct the ChatGroq client for this process's configured model.

    Single responsibility: configuration → client. No streaming and no error
    translation of its own.
    """
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
    """Normalize a chunk's usage metadata to the shape the SSE contract uses.

    Groq reports usage only on the final streamed chunk, via ``x_groq.usage``,
    and may omit it entirely. Absence is an expected state, not a fault, so it
    is a plain ``None`` return rather than an exception or a local try/except.
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
    """Accumulate a LangChain chunk stream into the SSE event contract.

    Kept separate from client construction so it can be exercised against a
    plain iterable of fake chunks — a bug in usage parsing or text
    accumulation is traceable to this function alone.

    Reads ``chunk.text`` rather than ``chunk.content``: ``.text`` yields the
    textual payload under both the v0 and v1 LangChain content formats, and
    excludes non-text blocks such as reasoning, so it cannot silently start
    emitting structured content if ``LC_OUTPUT_VERSION`` is set in the
    environment.
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
            rendered by ``build_prompt``. Sent as a single ``HumanMessage``,
            matching the original implementation's user-role framing; the
            prompt's instructions are authored as user content, and promoting
            them to a system message would change model behavior.

    Yields:
        Token events during streaming, then a final done event with usage.
    """
    llm = build_llm()
    yield from _stream_tokens(llm.stream([HumanMessage(content=system_prompt)]))
