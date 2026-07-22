"""Integration tests for auth routes (/auth/register, /auth/login).

Tests: registration success/failure, login success/failure, role in token claims.
"""

import pytest
from app.auth.jwt import decode_access_token


class TestRegister:
    """Tests for POST /auth/register."""

    def test_register_success(self, client):
        """New user registration returns 201 with a valid token."""
        response = client.post("/auth/register", json={
            "email": "newuser@test.com",
            "password": "securepassword",
            "role": "viewer",
        })
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "viewer"

    def test_register_admin_role(self, client):
        """Registration with admin role succeeds and token has admin role."""
        response = client.post("/auth/register", json={
            "email": "admin@newtest.com",
            "password": "adminpass",
            "role": "admin",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "admin"
        # Verify the token also contains the correct role claim
        payload = decode_access_token(data["access_token"])
        assert payload["role"] == "admin"

    def test_register_duplicate_email(self, client):
        """Registering the same email twice returns 409."""
        user_data = {
            "email": "duplicate@test.com",
            "password": "password123",
            "role": "viewer",
        }
        client.post("/auth/register", json=user_data)
        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 409

    def test_register_invalid_email(self, client):
        """Registration with invalid email format returns 422."""
        response = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "password123",
            "role": "viewer",
        })
        assert response.status_code == 422


class TestLogin:
    """Tests for POST /auth/login."""

    def test_login_success(self, client):
        """Registered user can login and gets a valid token."""
        # First register
        client.post("/auth/register", json={
            "email": "loginuser@test.com",
            "password": "mypassword",
            "role": "manager",
        })
        # Then login
        response = client.post("/auth/login", json={
            "email": "loginuser@test.com",
            "password": "mypassword",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "manager"

    def test_login_wrong_password(self, client):
        """Login with incorrect password returns 401."""
        client.post("/auth/register", json={
            "email": "wrongpw@test.com",
            "password": "correctpassword",
            "role": "viewer",
        })
        response = client.post("/auth/login", json={
            "email": "wrongpw@test.com",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    def test_login_nonexistent_user(self, client):
        """Login with unregistered email returns 401."""
        response = client.post("/auth/login", json={
            "email": "noone@test.com",
            "password": "password123",
        })
        assert response.status_code == 401

    def test_login_role_in_token(self, client):
        """Token claims contain the correct role after login."""
        client.post("/auth/register", json={
            "email": "rolecheck@test.com",
            "password": "password123",
            "role": "admin",
        })
        response = client.post("/auth/login", json={
            "email": "rolecheck@test.com",
            "password": "password123",
        })
        data = response.json()
        payload = decode_access_token(data["access_token"])
        assert payload["sub"] == "rolecheck@test.com"
        assert payload["role"] == "admin"

    def test_each_role_can_login(self, client):
        """All three roles (viewer, manager, admin) can register and login."""
        for role in ["viewer", "manager", "admin"]:
            email = f"{role}@roletest.com"
            client.post("/auth/register", json={
                "email": email,
                "password": "password123",
                "role": role,
            })
            response = client.post("/auth/login", json={
                "email": email,
                "password": "password123",
            })
            assert response.status_code == 200
            assert response.json()["role"] == role
