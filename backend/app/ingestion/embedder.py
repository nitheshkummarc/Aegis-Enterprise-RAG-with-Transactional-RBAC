"""Embedding generation for document chunks and search queries.

Embeddings run on OpenAI; text generation runs on Groq (see
app.retrieval.generate). This module is the only place an embedding client is
constructed, so the request path, the ingestion worker, the corpus generator
and the evaluation harness all share one implementation.

Error handling follows the convention used across the generation and
observability layers: missing configuration raises ConfigurationError, an
empty input is handled as a precondition, and provider errors propagate to
the caller so the ingestion worker's retry logic can act on them.
"""

import openai

from app.config import EMBEDDING_DIMENSIONS, get_settings
from app.core.exceptions import ConfigurationError


def _require_setting(name: str) -> str:
    """Return a required non-empty setting, or raise ConfigurationError."""
    value = (getattr(get_settings(), name, "") or "").strip()
    if not value:
        raise ConfigurationError(
            f"{name} is not set. Embedding generation requires it. "
            f"Set {name} in backend/.env (see .env.example)."
        )
    return value


def embedding_model_name() -> str:
    """Return the configured embedding model identifier."""
    return _require_setting("EMBEDDING_MODEL")


def build_embedding_client() -> openai.OpenAI:
    """Construct the OpenAI client used for embedding requests."""
    return openai.OpenAI(api_key=_require_setting("OPENAI_API_KEY"))


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts.

    Args:
        texts: Text strings to embed.

    Returns:
        One vector per input, in input order, each EMBEDDING_DIMENSIONS wide.

    Raises:
        ConfigurationError: If OPENAI_API_KEY or EMBEDDING_MODEL is unset.
        openai.RateLimitError: On HTTP 429; the caller may retry.
        openai.APIError: For other provider errors.
    """
    if not texts:
        return []

    client = build_embedding_client()
    response = client.embeddings.create(
        model=embedding_model_name(),
        input=texts,
    )

    # Response order is not guaranteed to match input order.
    sorted_data = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in sorted_data]


def embed_query(text: str) -> list[float]:
    """Generate an embedding for a single query string."""
    vectors = embed_texts([text])
    if not vectors:
        raise ConfigurationError(
            "Embedding provider returned no vector for a non-empty query. "
            f"Check that '{embedding_model_name()}' is available to this account."
        )
    return vectors[0]


def verify_embedding_dimensions() -> int:
    """Check the model's output width against the configured value.

    Returns:
        The measured width, when it matches EMBEDDING_DIMENSIONS.

    Raises:
        ConfigurationError: If the widths differ. A mismatch means embeddings
            cannot be written to the pgvector column.
    """
    measured = len(embed_query("dimension probe"))
    if measured != EMBEDDING_DIMENSIONS:
        raise ConfigurationError(
            f"Embedding width mismatch: '{embedding_model_name()}' returned "
            f"{measured}-dimensional vectors, but EMBEDDING_DIMENSIONS is "
            f"{EMBEDDING_DIMENSIONS}. Update EMBEDDING_DIMENSIONS and "
            "app/db/schema.sql, then rebuild the database and re-seed."
        )
    return measured
