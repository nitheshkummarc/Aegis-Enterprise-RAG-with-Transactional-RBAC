"""JWT token creation and verification."""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from app.config import get_settings


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token.
    
    Args:
        data: Claims to encode in the token. Must include 'sub' (user email)
              and 'role' (user role).
        expires_delta: Optional custom expiration. Defaults to JWT_EXPIRE_MINUTES
                       from settings.
    
    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT access token.
    
    Args:
        token: The encoded JWT string.
    
    Returns:
        The decoded token payload.
    
    Raises:
        ExpiredSignatureError: If the token has expired.
        InvalidTokenError: If the token is invalid.
    """
    settings = get_settings()
    
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return payload
