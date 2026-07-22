"""Unit tests for JWT token creation and verification.

Tests: token creation, correct claims, expiry rejection, invalid token rejection.
"""

import time
from datetime import timedelta

import pytest
import jwt as pyjwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.auth.jwt import create_access_token, decode_access_token


class TestCreateAccessToken:
    """Tests for create_access_token."""

    def test_returns_string(self):
        """Token creation returns a non-empty string."""
        token = create_access_token({"sub": "user@test.com", "role": "viewer"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_correct_claims(self):
        """Decoded token has the expected sub, role, and exp claims."""
        token = create_access_token({"sub": "user@test.com", "role": "admin"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_custom_expiry(self):
        """Token respects a custom expiration delta."""
        token = create_access_token(
            {"sub": "user@test.com", "role": "viewer"},
            expires_delta=timedelta(minutes=5),
        )
        payload = decode_access_token(token)
        assert "exp" in payload


class TestDecodeAccessToken:
    """Tests for decode_access_token."""

    def test_valid_token_decodes(self):
        """A freshly created token decodes without errors."""
        token = create_access_token({"sub": "user@test.com", "role": "manager"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user@test.com"
        assert payload["role"] == "manager"

    def test_expired_token_raises(self):
        """An expired token raises ExpiredSignatureError."""
        token = create_access_token(
            {"sub": "user@test.com", "role": "viewer"},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(ExpiredSignatureError):
            decode_access_token(token)

    def test_invalid_token_raises(self):
        """A tampered token raises an error on decode."""
        token = create_access_token({"sub": "user@test.com", "role": "viewer"})
        tampered = token + "tampered"
        with pytest.raises(Exception):  # InvalidTokenError or DecodeError
            decode_access_token(tampered)

    def test_wrong_secret_raises(self):
        """A token signed with a different secret fails verification."""
        # Manually create a token with a wrong secret
        wrong_token = pyjwt.encode(
            {"sub": "user@test.com", "role": "viewer", "exp": 9999999999},
            "wrong-secret-key",
            algorithm="HS256",
        )
        with pytest.raises(Exception):  # InvalidSignatureError
            decode_access_token(wrong_token)
