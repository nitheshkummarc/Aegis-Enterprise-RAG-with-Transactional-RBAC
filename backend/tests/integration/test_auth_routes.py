"""Integration tests for auth routes (/auth/register, /auth/login).

RegisterRequest has no `role` field and forbids unknown ones (extra="forbid")
— every self-registered user is a viewer. Non-viewer test users are seeded
directly via the DB (conftest's admin_user/manager_user/viewer_user
fixtures), not through the public register endpoint.

Tests: registration success/failure, mass-assignment rejection, login
success/failure, role in token claims.
"""

import pytest
from app.auth.jwt import decode_access_token


class TestRegister:
    """Tests for POST /auth/register."""

    def test_register_success(self, client):
        """New user registration returns 201 with a valid token, role forced
        to viewer."""
        response = client.post("/auth/register", json={
            "email": "newuser@test.com",
            "password": "securepassword",
        })
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "viewer"

    def test_register_rejects_role_field(self, client):
        """A client-supplied role is rejected outright (mass-assignment
        protection), not silently ignored."""
        response = client.post("/auth/register", json={
            "email": "wannabe-admin@test.com",
            "password": "securepassword",
            "role": "admin",
        })
        assert response.status_code == 422

    def test_register_duplicate_email(self, client):
        """Registering the same email twice returns 409."""
        user_data = {
            "email": "duplicate@test.com",
            "password": "password123",
        }
        client.post("/auth/register", json=user_data)
        response = client.post("/auth/register", json=user_data)
        assert response.status_code == 409

    def test_register_invalid_email(self, client):
        """Registration with invalid email format returns 422."""
        response = client.post("/auth/register", json={
            "email": "not-an-email",
            "password": "password123",
        })
        assert response.status_code == 422


class TestLogin:
    """Tests for POST /auth/login."""

    def test_login_success(self, client):
        """Registered user can login and gets a valid token."""
        client.post("/auth/register", json={
            "email": "loginuser@test.com",
            "password": "mypassword",
        })
        response = client.post("/auth/login", json={
            "email": "loginuser@test.com",
            "password": "mypassword",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["role"] == "viewer"

    def test_login_wrong_password(self, client):
        """Login with incorrect password returns 401."""
        client.post("/auth/register", json={
            "email": "wrongpw@test.com",
            "password": "correctpassword",
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

    def test_login_role_in_token(self, client, admin_user):
        """Token claims contain the correct role after login."""
        response = client.post("/auth/login", json={
            "email": admin_user.email,
            "password": "adminpass",
        })
        data = response.json()
        payload = decode_access_token(data["access_token"])
        assert payload["sub"] == admin_user.email
        assert payload["role"] == "admin"

    def test_each_seeded_role_can_login(
        self, client, viewer_user, manager_user, admin_user
    ):
        """All three roles can login and get their own role back."""
        cases = [
            (viewer_user, "viewerpass", "viewer"),
            (manager_user, "managerpass", "manager"),
            (admin_user, "adminpass", "admin"),
        ]
        for user, password, expected_role in cases:
            response = client.post("/auth/login", json={
                "email": user.email,
                "password": password,
            })
            assert response.status_code == 200
            assert response.json()["role"] == expected_role
