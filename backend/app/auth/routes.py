"""Authentication routes: /register and /login."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.core.security import hash_password, verify_password
from app.db.session import get_db
from app.db.models import User, UserRole

router = APIRouter()


# ---- Request / Response Schemas ----

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole = UserRole.viewer


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


# ---- Routes ----

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user with hashed password."""
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
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return TokenResponse(access_token=token, role=user.role.value)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
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
