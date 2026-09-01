"""Groq embedding generation, for both ingestion and query time.

Groq exposes an OpenAI-compatible wire protocol, so the `openai` package is
reused here as a generic HTTP client pointed at ``GROQ_API_BASE``. That is a
protocol choice, not a dependency on an OpenAI account: nothing in this tree
reads an OpenAI credential, and the only key the system needs is
``GROQ_API_KEY``.

This module is the single place an embedding client is constructed. The
request path, the ingestion worker, the corpus generator and the evaluation
harness all embed through :func:`embed_texts` or :func:`embed_query` rather
than building their own client — before this, three separate files each stood
up their own, and each would have had to be found and fixed independently on
a provider change.

Error policy — the same three tiers used across the generation layer and
``app.core.observability``:

1. **Misconfiguration** (no ``GROQ_API_KEY``, blank model) raises
   :class:`ConfigurationError`. Never caught, never degraded.
2. **Expected absence** (an empty batch) is a precondition check returning a
   trivial result. No ``try``/``except``.
3. **Provider faults** propagate to the caller. Rate limits surface as
   ``openai.RateLimitError`` — which the `openai` client raises for any HTTP
   429 regardless of host — so the ingestion worker's existing retry/backoff
   keeps working unchanged.
"""

import openai

from app.config import EMBEDDING_DIMENSIONS, get_settings
from app.core.exceptions import ConfigurationError


def _require_setting(name: str) -> str:
    """Read a required non-empty setting, or fail loudly.

    Mirrors the helper in ``app.retrieval.generate``: a missing credential is
    a deployment fault an operator must see, not something to translate into
    a generic retryable error.
    """
    value = (getattr(get_settings(), name, "") or "").strip()
    if not value:
        raise ConfigurationError(
            f"{name} is not set. Groq embeddings cannot run without it. "
            f"Set {name} in backend/.env (see .env.example)."
        )
    return value


def embedding_model_name() -> str:
    """The Groq embedding model this process uses."""
    return _require_setting("GROQ_EMBEDDING_MODEL")


def build_embedding_client() -> openai.OpenAI:
    """Construct the Groq-backed embedding client.

    Single responsibility: configuration → client. The `base_url` is what
    makes this Groq rather than OpenAI; without it the same class would talk
    to a provider this project no longer uses.
    """
    settings = get_settings()
    return openai.OpenAI(
        api_key=_require_setting("GROQ_API_KEY"),
        base_url=settings.GROQ_API_BASE,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    Args:
        texts: Text strings to embed.

    Returns:
        One vector per input, in input order, each ``EMBEDDING_DIMENSIONS``
        floats wide.

    Raises:
        ConfigurationError: If GROQ_API_KEY or GROQ_EMBEDDING_MODEL is unset.
        openai.RateLimitError: On HTTP 429 (the caller may retry).
        openai.APIError: For other provider errors.
    """
    if not texts:
        return []

    client = build_embedding_client()
    response = client.embeddings.create(
        model=embedding_model_name(),
        input=texts,
    )

    # Sort by index: the API does not guarantee response order matches input,
    # and a silent reordering would attach every embedding to the wrong chunk.
    sorted_data = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in sorted_data]


def embed_query(text: str) -> list[float]:
    """Embed a single query string.

    A thin wrapper over :func:`embed_texts` so the request path and the
    evaluation harness share one implementation instead of each unpacking
    ``response.data[0]`` themselves.
    """
    vectors = embed_texts([text])
    if not vectors:
        raise ConfigurationError(
            "Embedding provider returned no vector for a non-empty query. "
            f"Check that '{embedding_model_name()}' is available to this "
            "Groq account."
        )
    return vectors[0]


def verify_embedding_dimensions() -> int:
    """Measure the model's real output width and check it against the schema.

    ``EMBEDDING_DIMENSIONS`` fixes the pgvector column width, so a mismatch
    means every embedding written from here would be rejected by the database
    — or, worse, that the column was created at a width the model does not
    produce. Raising is the only safe response; there is no degraded mode in
    which a wrong vector width is usable.

    Returns:
        The measured width, when it matches.
    """
    measured = len(embed_query("dimension probe"))
    if measured != EMBEDDING_DIMENSIONS:
        raise ConfigurationError(
            f"Embedding width mismatch: '{embedding_model_name()}' returned "
            f"{measured}-dimensional vectors, but EMBEDDING_DIMENSIONS in "
            f"app/config.py is {EMBEDDING_DIMENSIONS}. Set it to {measured}, "
            "update app/db/schema.sql and the initial migration to match, "
            "then rebuild the database and re-seed the corpus. Do not paper "
            "over this — the pgvector column width is not negotiable at "
            "insert time."
        )
    return measured
