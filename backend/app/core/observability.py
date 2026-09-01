"""Langfuse client wiring, shared by the retrieval route and generation layer.

Resolves the Langfuse v4 client from settings and provides the LangChain
callback used to report generation spans. Centralised so the route and the
generation layer use one client and one configuration path.

Behaviour when Langfuse is unavailable:

* Not configured (no keys) — returns None; tracing is skipped.
* SDK API mismatch — raises ConfigurationError.
* Runtime fault (network, auth, exporter) — logged via _degrade() and
  tracing is disabled for the process.
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

# Methods the v4 client must expose.
_REQUIRED_V4_CLIENT_API = ("start_as_current_observation", "flush")

# The client owns a background exporter thread, so build it once per process.
_UNSET = object()
_client_cache: Any = _UNSET


def _degrade(event: str, exc: BaseException) -> None:
    """Log a recoverable observability fault and disable tracing."""
    logger.warning(
        "observability degraded: tracing disabled for this process "
        "(component=%s event=%s error=%s: %s)",
        COMPONENT,
        event,
        type(exc).__name__,
        exc,
    )


def is_enabled() -> bool:
    """Return True when both Langfuse keys are configured."""
    settings = get_settings()
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def _assert_v4_api(client: "Langfuse") -> None:
    """Raise ConfigurationError if the client lacks the expected v4 API."""
    missing = [name for name in _REQUIRED_V4_CLIENT_API if not hasattr(client, name)]
    if missing:
        raise ConfigurationError(
            "The installed Langfuse SDK does not expose the expected v4 "
            f"client API (missing: {', '.join(missing)}). Aegis requires "
            "langfuse>=3. Update the dependency or app/core/observability.py."
        )


def _build_client() -> "Langfuse":
    """Construct and validate the Langfuse client.

    Keys are passed explicitly because pydantic-settings loads .env into
    Settings without exporting to os.environ.
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
    """Return the process-wide Langfuse client, or None if tracing is off."""
    global _client_cache

    if _client_cache is not _UNSET:
        return _client_cache

    if not is_enabled():
        _client_cache = None
        return None

    try:
        _client_cache = _build_client()
    except ConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - degrades to tracing disabled
        _degrade("client_init_failed", exc)
        _client_cache = None

    return _client_cache


def tracing_callbacks() -> list:
    """Return LangChain callbacks that report spans to Langfuse.

    Returns an empty list when tracing is unavailable. The handler binds to
    the current OpenTelemetry context, so the generation span nests under
    whichever observation is active.
    """
    if get_client() is None:
        return []

    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception as exc:  # noqa: BLE001 - degrades to tracing disabled
        _degrade("langchain_callback_unavailable", exc)
        return []


def reset_cache() -> None:
    """Clear the cached client, for tests that change settings."""
    global _client_cache
    _client_cache = _UNSET
