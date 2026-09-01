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
    """Raised when the process is misconfigured and cannot recover at runtime.

    Covers missing credentials, unset model identifiers, and installed SDKs
    whose API does not match the calling code. Not an HTTPException: these are
    server-side deployment faults rather than client errors, and should not be
    translated into a 4xx response.
    """
