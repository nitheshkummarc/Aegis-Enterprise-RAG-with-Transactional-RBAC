"""Custom exception classes for Aegis."""

from fastapi import HTTPException, status


class CredentialsException(HTTPException):
    """Raised when authentication credentials are invalid."""
    def __init__(self, detail: str = "Could not validate credentials"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(HTTPException):
    """Raised when a user lacks the required role."""
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class ConfigurationError(RuntimeError):
    """Raised when the process is misconfigured in a way that cannot be
    recovered from at runtime — a missing required credential, a blank
    model name, or an installed SDK whose API no longer matches the code
    calling it.

    Deliberately NOT an HTTPException: these are server-side deployment
    faults, not client errors, and they must surface loudly rather than be
    translated into a tidy 4xx. Nothing in the codebase may catch this
    broadly. It exists because the opposite policy — a bare
    ``except Exception`` around optional setup — is exactly how the
    Langfuse v2/v4 API mismatch stayed invisible for months while every
    trace span in the query path was silently skipped.
    """
