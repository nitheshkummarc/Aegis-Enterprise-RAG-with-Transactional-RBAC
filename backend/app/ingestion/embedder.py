"""OpenAI embedding generation for document chunks.

Uses the text-embedding-3-small model (1536 dimensions).
"""

import openai

from app.config import get_settings


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts using OpenAI.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors (each a list of 1536 floats).

    Raises:
        openai.RateLimitError: If the API rate limit is exceeded (caller should retry).
        openai.APIError: For other API errors.
    """
    settings = get_settings()
    client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )

    # Sort by index to ensure order matches input
    sorted_data = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in sorted_data]
