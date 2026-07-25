"""FastAPI dependencies for authentication and authorization."""

from typing import Annotated

from fastapi import Depends, Header
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
from jwt.exceptions import InvalidTokenError, ExpiredSignatureError

from app.auth.jwt import decode_access_token
from app.core.exceptions import CredentialsException, ForbiddenException
from app.db.session import get_db
from app.db.models import User, UserRole


class TokenPayload(BaseModel):
    sub: str
    role: UserRole


def get_current_user(
    authorization: Annotated[str, Header()],
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the current user from the Authorization header.
    
    Expects: Authorization: Bearer <token>
    """
    if not authorization.startswith("Bearer "):
        raise CredentialsException("Invalid authorization header format")
    
    token = authorization[len("Bearer "):]
    
    try:
        payload = decode_access_token(token)
    except ExpiredSignatureError:
        raise CredentialsException("Token has expired")
    except InvalidTokenError:
        raise CredentialsException("Invalid token")
    
    try:
        token_data = TokenPayload(**payload)
    except ValidationError:
        raise ForbiddenException("Invalid token payload")
    
    email = token_data.sub
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise CredentialsException("User not found")
    
    return user


def require_role(*allowed_roles: UserRole):
    """Factory that returns a dependency requiring the user to have one of the allowed roles.
    
    Usage:
        @router.post("/admin-only", dependencies=[Depends(require_role(UserRole.admin))])
    """
    def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise ForbiddenException(
                f"Role '{current_user.role.value}' is not permitted. "
                f"Required: {[r.value for r in allowed_roles]}"
            )
        return current_user
    return role_checker
