"""Measure the real output width of the configured Groq embedding model.

    cd backend
    python -m scripts.verify_embedding_dimensions

``EMBEDDING_DIMENSIONS`` in ``app/config.py`` fixes the pgvector column width.
It must equal what the model actually returns — a documented figure is not
good enough, because a hosted copy of a model may truncate (nomic-embed-text
supports Matryoshka widths from 64 to 768) or may not expose that behavior at
all. This script settles it with one live call and prints exactly what to
change if the configured value is wrong.

Run it once when a GROQ_API_KEY is first issued, and again whenever
GROQ_EMBEDDING_MODEL changes.
"""

import sys

from app.config import EMBEDDING_DIMENSIONS
from app.core.exceptions import ConfigurationError
from app.ingestion.embedder import embed_query, embedding_model_name

# Files carrying the width as a literal, which must be edited together.
_LITERAL_SITES = (
    "app/config.py            EMBEDDING_DIMENSIONS",
    "app/db/schema.sql        embedding vector(...)",
    "app/db/migrations/versions/001_initial_schema.py   embedding VECTOR(...)",
)


def main() -> int:
    try:
        model = embedding_model_name()
    except ConfigurationError as exc:
        print(f"FAIL: {exc}")
        return 2

    print(f"Probing '{model}' at Groq's OpenAI-compatible endpoint...")

    try:
        vector = embed_query("dimension probe")
    except ConfigurationError as exc:
        print(f"FAIL: {exc}")
        return 2
    except Exception as exc:  # provider fault — report it verbatim, don't mask
        print(f"FAIL: the embedding call did not succeed.\n  {type(exc).__name__}: {exc}")
        print(
            "\nIf this is a 404/model_not_found, the account may not have access "
            "to this embedding model. Groq's embeddings endpoint exists but is "
            "not listed in the public API reference, so availability is worth "
            "confirming in the console before assuming a code fault."
        )
        return 2

    measured = len(vector)
    print(f"  measured width : {measured}")
    print(f"  configured     : {EMBEDDING_DIMENSIONS}")

    if measured == EMBEDDING_DIMENSIONS:
        print("\nOK — configuration matches the model. No changes needed.")
        return 0

    print(f"\nMISMATCH. Set the width to {measured} in each of:")
    for site in _LITERAL_SITES:
        print(f"  - {site}")
    print(
        "\nThen rebuild the database and re-seed:\n"
        "  python -m scripts.seed_users\n"
        "  python -m scripts.generate_synthetic_corpus\n"
        "\nThis is a schema change, not a config tweak: existing vectors are "
        "the wrong width and cannot be reused."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
