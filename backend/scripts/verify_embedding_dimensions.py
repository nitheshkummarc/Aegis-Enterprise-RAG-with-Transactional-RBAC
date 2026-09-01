"""Check the configured embedding model's output width.

    cd backend
    python -m scripts.verify_embedding_dimensions

EMBEDDING_DIMENSIONS determines the pgvector column width, so it must equal
the width the model actually returns. This script makes one embedding request
and reports whether the configured value matches, along with the files to
update if it does not.
"""

import sys

from app.config import EMBEDDING_DIMENSIONS
from app.core.exceptions import ConfigurationError
from app.ingestion.embedder import embed_query, embedding_model_name

# Locations that must be updated together when the width changes.
_LITERAL_SITES = (
    "backend/.env             EMBEDDING_DIMENSIONS",
    "app/db/schema.sql        embedding vector(...)",
)


def main() -> int:
    try:
        model = embedding_model_name()
    except ConfigurationError as exc:
        print(f"FAIL: {exc}")
        return 2

    print(f"Requesting an embedding from '{model}'...")

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
