"""Langfuse (v4) wiring, shared by the retrieval route and the generation layer.

Why this module exists
----------------------
Both the retrieval span (hand-rolled, because a SQL query is not a LangChain
operation) and the generation span (automatic, via LangChain's callback
protocol) need the *same* Langfuse client, resolved from the *same* settings,
with the *same* failure policy. Answering "is tracing configured?" and
"give me the client" in one place is what keeps ``routes.py`` and
``generate.py`` from growing two divergent copies of that logic.

It also exists as a regression guard. The previous implementation called the
v2-era ``langfuse.trace(...)`` against an installed v4 SDK. The resulting
``AttributeError`` was swallowed by a bare ``except Exception``, so every
span in the query path was skipped and the only symptom was an empty
dashboard. :func:`_build_client` now verifies the v4 API surface up front and
raises :class:`ConfigurationError` if it is missing, so the next SDK break is
a startup failure instead of months of silent data loss.

Failure policy (the single pattern used across this migration)
--------------------------------------------------------------
1. **Not configured** — no Langfuse keys. An expected, supported state, so it
   is a precondition check that returns ``None``. Not an exception, and never
   a ``try``/``except``.
2. **Misconfigured** — keys present but the SDK API does not match. Raises
   :class:`ConfigurationError`. Never swallowed.
3. **Unexpected runtime fault** — network, auth rejection, exporter failure.
   Degrades to "tracing off" through :func:`_degrade`, the one helper that is
   allowed to catch broadly, so the log format is identical everywhere and
   there is exactly one place to look when traces go missing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.core.exceptions import ConfigurationError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

COMPONENT = "observability"

# Methods the v4 client must expose. If the installed SDK lacks any of these,
# the code in this repo is calling an API that no longer exists — the exact
# failure mode that went undetected before.
_REQUIRED_V4_CLIENT_API = ("start_as_current_observation", "flush")

# Module-level cache. The client owns a background OTEL exporter thread, so it
# must be built once per process, not once per request as the old code did.
_UNSET = object()
_client_cache: Any = _UNSET


def _degrade(event: str, exc: BaseException) -> None:
    """Record a recoverable observability fault in one consistent format.

    The only place in this migration permitted to catch broadly. Tracing is
    optional, so a fault here must never take a user's query down with it —
    but it must still be visible, which is what the previous silent
    ``except Exception: pass`` failed to do.
    """
    logger.warning(
        "observability degraded: tracing disabled for this process "
        "(component=%s event=%s error=%s: %s)",
        COMPONENT,
        event,
        type(exc).__name__,
        exc,
    )


def is_enabled() -> bool:
    """True when both Langfuse keys are configured.

    The single source of truth for this question. Both the route and the
    generation layer consult it rather than re-checking the settings fields.
    """
    settings = get_settings()
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def _assert_v4_api(client: "Langfuse") -> None:
    """Fail loudly if the installed SDK is not the v4 API this code targets."""
    missing = [name for name in _REQUIRED_V4_CLIENT_API if not hasattr(client, name)]
    if missing:
        raise ConfigurationError(
            "Installed Langfuse SDK does not expose the v4 client API this "
            f"code targets (missing: {', '.join(missing)}). Aegis requires "
            "langfuse>=3. Pin the dependency or update app/core/observability.py "
            "to the installed SDK's API — do not catch this to keep the app "
            "booting, which is how the previous v2/v4 mismatch went unnoticed."
        )


def _build_client() -> "Langfuse":
    """Construct the Langfuse v4 client from settings and validate its API.

    Keys are passed explicitly rather than left to the SDK's own environment
    lookup: pydantic-settings loads ``.env`` into :class:`Settings` without
    exporting to ``os.environ``, so the SDK would otherwise see nothing.
    """
    from langfuse import Langfuse

    settings = get_settings()
    client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
    _assert_v4_api(client)
    return client


def get_client() -> "Langfuse | None":
    """Return the process-wide Langfuse client, or ``None`` if tracing is off.

    ``None`` means "not configured" (tier 1) or "faulted and degraded"
    (tier 3). A misconfigured SDK (tier 2) raises instead.
    """
    global _client_cache

    if _client_cache is not _UNSET:
        return _client_cache

    if not is_enabled():
        _client_cache = None
        return None

    try:
        _client_cache = _build_client()
    except ConfigurationError:
        # Tier 2 — a real API mismatch. Must surface, never degrade.
        raise
    except Exception as exc:  # noqa: BLE001 - the one sanctioned broad catch
        _degrade("client_init_failed", exc)
        _client_cache = None

    return _client_cache


def tracing_callbacks() -> list:
    """LangChain callbacks that route LLM spans into the active Langfuse trace.

    Returns ``[]`` when tracing is unavailable, which LangChain accepts as
    "no callbacks" — so callers need no conditional of their own.

    The handler binds to Langfuse's OpenTelemetry context rather than to an
    explicit parent, so the generation span nests under whatever observation
    is current when the LLM runs. That is what replaces the old hand-rolled
    ``trace.span("2. LLM Generation")``: LangChain now reports the model name,
    the prompt, the completion, and token usage itself.
    """
    if get_client() is None:
        return []

    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception as exc:  # noqa: BLE001 - the one sanctioned broad catch
        _degrade("langchain_callback_unavailable", exc)
        return []


def reset_cache() -> None:
    """Drop the cached client. For tests that swap settings between cases."""
    global _client_cache
    _client_cache = _UNSET
