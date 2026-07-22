"""Password hashing and verification using bcrypt directly.

Never store or compare plaintext passwords. This module is the single
place in the codebase where password hashing happens.

Note: Using bcrypt directly instead of passlib[bcrypt] because passlib
does not support bcrypt>=5.0.0 (missing __about__ attribute). The Master
Build Prompt allows either approach.
"""

import bcrypt


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    password_bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its bcrypt hash."""
    password_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(password_bytes, hashed_bytes)
