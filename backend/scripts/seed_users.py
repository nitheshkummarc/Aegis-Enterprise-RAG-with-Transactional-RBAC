"""Seed script: creates one admin, one manager, and one viewer test user.

Usage:
    cd backend
    python -m scripts.seed_users
"""

import sys
import os

# Ensure the backend directory is on the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import Session
from app.db.session import get_engine
from app.db.models import User, UserRole
from app.core.security import hash_password
from sqlalchemy.orm import sessionmaker


SEED_USERS = [
    {"email": "admin@clearancerag.test", "password": "admin123", "role": UserRole.admin},
    {"email": "manager@clearancerag.test", "password": "manager123", "role": UserRole.manager},
    {"email": "viewer@clearancerag.test", "password": "viewer123", "role": UserRole.viewer},
]


def seed(db: Session) -> None:
    """Insert seed users if they don't already exist."""
    for user_data in SEED_USERS:
        existing = db.query(User).filter(User.email == user_data["email"]).first()
        if existing:
            print(f"  User {user_data['email']} already exists, skipping.")
            continue
        user = User(
            email=user_data["email"],
            password_hash=hash_password(user_data["password"]),
            role=user_data["role"],
        )
        db.add(user)
        print(f"  Created {user_data['role'].value}: {user_data['email']}")
    db.commit()


if __name__ == "__main__":
    print("Seeding test users...")
    engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        seed(db)
    print("Done.")
