"""Custom exception classes for ClearanceRAG."""

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
