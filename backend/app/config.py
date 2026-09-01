"""Application configuration loaded from environment variables via pydantic-settings."""

from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


# Width of the vectors GROQ_EMBEDDING_MODEL produces, and therefore the width
# of the pgvector column, the ORM type, and every fixture that builds a fake
# vector. It is a module constant rather than a Settings field on purpose:
# changing it is a schema change requiring a rebuild, not something an
# environment variable may quietly disagree with the database about.
#
# THIS VALUE MUST MATCH THE MODEL'S REAL OUTPUT. It has NOT been confirmed
# against a live Groq call yet — nomic-embed-text-v1.5 is natively 768-wide
# and supports Matryoshka truncation, and Groq's hosted copy may or may not
# expose that. Run `python -m scripts.verify_embedding_dimensions` once a
# GROQ_API_KEY is available; it measures the real width and tells you what to
# put here. `verify_embedding_dimensions()` in app.ingestion.embedder enforces
# the match at runtime so a wrong value can never silently build a corpus the
# database will reject.
EMBEDDING_DIMENSIONS = 768


class Settings(BaseSettings):
    """Aegis application settings.
    
    All variable names match the .env.example exactly.
    """
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql+psycopg://clearancerag:clearancerag@localhost:5432/clearancerag"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Groq — the only model provider. One key covers both generation and
    # embeddings; there is no OpenAI account dependency anywhere in the tree.
    #
    # GROQ_MODEL selects which chat model the whole process serves. It is
    # resolved once at startup through the lru_cached get_settings(), so
    # switching models means restarting the process — which is fine: the eval
    # harness runs as a fresh process per invocation.
    #
    # Re-verify both IDs against Groq's live catalog before relying on them.
    # That catalog churns, and llama-3.3-70b-versatile was already retired
    # from the free tier out from under this project once.
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_EMBEDDING_MODEL: str = "nomic-embed-text-v1_5"
    GROQ_API_KEY: str = ""

    # Groq speaks the OpenAI wire protocol, so the `openai` package is reused
    # as a generic HTTP client pointed here. That is a protocol choice, not a
    # dependency on an OpenAI account.
    GROQ_API_BASE: str = "https://api.groq.com/openai/v1"
    
    # JWT
    JWT_SECRET_KEY: str = "change-me-to-a-random-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    
    # NextAuth
    NEXTAUTH_SECRET: str = ""
    NEXTAUTH_URL: str = "http://localhost:3000"
    
    # Backend
    BACKEND_URL: str = "http://localhost:8000"
    
    # CORS (comma-separated origins, e.g. "http://localhost:3000,https://myapp.com")
    CORS_ORIGINS: str = "http://localhost:3000"

    # Comma-separated IPs of trusted reverse proxies (nginx, load balancer).
    # X-Forwarded-For is only honored for the rate limiter when the direct
    # connection IP is in this set — otherwise any client could rotate the
    # header to bypass rate limiting. Empty by default (no proxy trusted).
    TRUSTED_PROXY_IPS: str = ""

    # How long (minutes) a Document may remain status="processing" with zero
    # associated chunks before the periodic cleanup task marks it "failed".
    STUCK_DOCUMENT_TIMEOUT_MINUTES: int = 60
    
    # Langfuse
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def validate_production_secrets(self) -> 'Settings':
        if self.ENVIRONMENT == "production":
            if len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters in production to prevent "
                    "brute-force attacks against the HMAC-SHA256 signature."
                )
            if not self.GROQ_API_KEY:
                raise ValueError(
                    "GROQ_API_KEY must be set in production. It is the only "
                    "provider credential the system needs — it covers both "
                    "generation and embeddings."
                )
        return self


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
