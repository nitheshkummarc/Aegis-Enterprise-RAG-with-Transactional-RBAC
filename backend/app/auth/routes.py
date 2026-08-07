"""Authentication routes: /register and /login."""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.core.limiter import limiter
from app.db.session import get_db
from app.db.models import User, UserRole

router = APIRouter()


# ---- Request / Response Schemas ----

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    # Role is NOT accepted from the client. All users register as viewers.
    # Admin promotion must happen through a separate admin-only endpoint
    # or direct database update.


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    token_type: str = "bearer"
    role: str


# ---- Routes ----

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user with hashed password.

    All users are created with role='viewer'. There is no way to self-assign
    a higher role through this endpoint.
    """
    # Check for existing user
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.viewer,  # Hardcoded — never from client input
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.email, "role": user.role.value})
    return TokenResponse(access_token=token, role=user.role.value)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({"sub": user.email, "role": user.role.value})
    return TokenResponse(access_token=token, role=user.role.value)
