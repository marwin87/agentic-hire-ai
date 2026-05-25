"""Unit tests for auth utilities (password hashing, JWT encoding/decoding)."""

import pytest
from datetime import datetime, timedelta, timezone
from typing import Any
import jwt as pyjwt

from src.auth import (
    hash_password,
    verify_password,
    encode_token,
    decode_token,
    validate_password_strength,
)
from src.config.settings import config


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password_returns_string(self) -> None:
        """Test that hash_password returns a string."""
        password = "SecurePass123"
        hashed = hash_password(password)
        assert isinstance(hashed, str)
        assert hashed.startswith("$argon2")  # argon2 format

    def test_verify_password_correct(self) -> None:
        """Test that verify_password succeeds with correct password."""
        password = "SecurePass123"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """Test that verify_password fails with incorrect password."""
        password = "SecurePass123"
        wrong_password = "WrongPass456"
        hashed = hash_password(password)
        assert verify_password(wrong_password, hashed) is False

    def test_hash_different_results(self) -> None:
        """Test that same password hashed twice produces different hashes (bcrypt salts)."""
        password = "SecurePass123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        # Different hashes due to random salt, but both should verify the password
        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestPasswordValidation:
    """Tests for password strength validation."""

    def test_valid_password(self) -> None:
        """Test that valid password passes validation."""
        password = "SecurePass123"
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None

    def test_password_too_short(self) -> None:
        """Test that short password fails validation."""
        password = "Short1A"  # 7 chars, less than min 8
        valid, error = validate_password_strength(password)
        assert valid is False
        assert error is not None and "at least 8 characters" in error

    def test_password_missing_digit(self) -> None:
        """Test that password without digit fails validation."""
        password = "NoDigitHere"
        valid, error = validate_password_strength(password)
        assert valid is False
        assert error is not None and "digit" in error.lower()

    def test_password_missing_uppercase(self) -> None:
        """Test that password without uppercase fails validation."""
        password = "nouppercase1"
        valid, error = validate_password_strength(password)
        assert valid is False
        assert error is not None and "uppercase" in error.lower()

    def test_password_exact_min_length(self) -> None:
        """Test that password at exact minimum length passes."""
        password = "Exact1AB"  # 8 chars with digit and uppercase
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None

    def test_password_long(self) -> None:
        """Test that long password passes."""
        password = "VeryLongAndSecurePassword123456"
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None


class TestJWTEncoding:
    """Tests for JWT token encoding and decoding."""

    def test_encode_token_returns_string(self) -> None:
        """Test that encode_token returns a valid JWT string."""
        data = {"user_id": "123", "email": "test@example.com"}
        token = encode_token(data, expires_in_minutes=60)
        assert isinstance(token, str)
        assert len(token.split(".")) == 3  # JWT has 3 parts: header.payload.signature

    def test_encode_token_access_type(self) -> None:
        """Test that access token is encoded with correct type."""
        data = {"user_id": "123"}
        token = encode_token(data, expires_in_minutes=60, token_type="access")
        decoded = pyjwt.decode(token, config.jwt_secret_key, algorithms=[config.jwt_algorithm])
        assert decoded["type"] == "access"

    def test_encode_token_refresh_type(self) -> None:
        """Test that refresh token is encoded with correct type."""
        data = {"user_id": "123"}
        token = encode_token(data, expires_in_minutes=43200, token_type="refresh")
        decoded = pyjwt.decode(token, config.jwt_secret_key, algorithms=[config.jwt_algorithm])
        assert decoded["type"] == "refresh"

    def test_decode_token_success(self) -> None:
        """Test that decode_token successfully decodes valid token."""
        data = {"user_id": "123", "email": "test@example.com"}
        token = encode_token(data, expires_in_minutes=60)
        decoded = decode_token(token)
        assert decoded["user_id"] == "123"
        assert decoded["email"] == "test@example.com"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_decode_token_expired(self) -> None:
        """Test that decode_token raises error for expired token."""
        data: dict[str, str] = {"user_id": "123"}
        # Create a token that expired 1 second ago
        now = datetime.now(timezone.utc)
        to_encode: dict[str, Any] = data.copy()
        to_encode.update({
            "exp": now - timedelta(seconds=1),
            "iat": now,
            "type": "access",
        })
        expired_token = pyjwt.encode(to_encode, config.jwt_secret_key, algorithm=config.jwt_algorithm)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(expired_token)

    def test_decode_token_invalid_signature(self) -> None:
        """Test that decode_token raises error for tampered token."""
        data = {"user_id": "123"}
        token = encode_token(data, expires_in_minutes=60)
        # Tamper with the token
        tampered_token = token[:-10] + "0000000000"  # Modify last 10 chars

        with pytest.raises(pyjwt.DecodeError):
            decode_token(tampered_token)

    def test_token_claims_included(self) -> None:
        """Test that token contains expected claims."""
        data = {"user_id": "456", "email": "user@example.com"}
        token = encode_token(data, expires_in_minutes=60, token_type="access")
        decoded = decode_token(token)

        # Check user data is preserved
        assert decoded["user_id"] == "456"
        assert decoded["email"] == "user@example.com"

        # Check standard JWT claims
        assert "exp" in decoded
        assert "iat" in decoded
        assert decoded["type"] == "access"

    def test_token_expiration_time(self) -> None:
        """Test that token expiration is set correctly."""
        data: dict[str, str] = {"user_id": "123"}
        expire_minutes = 60
        before_encode = datetime.now(timezone.utc)
        token = encode_token(data, expires_in_minutes=expire_minutes)
        after_encode = datetime.now(timezone.utc)

        decoded = decode_token(token)
        exp_datetime = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)

        # Token expiration should be approximately expire_minutes from encoding time
        expected_min = before_encode + timedelta(minutes=expire_minutes - 1)
        expected_max = after_encode + timedelta(minutes=expire_minutes + 1)
        assert expected_min <= exp_datetime <= expected_max

    def test_refresh_token_longer_expiration(self) -> None:
        """Test that refresh tokens have longer expiration than access tokens."""
        data: dict[str, str] = {"user_id": "123"}
        access_token = encode_token(data, expires_in_minutes=60, token_type="access")
        refresh_token = encode_token(data, expires_in_minutes=43200, token_type="refresh")

        access_decoded = decode_token(access_token)
        refresh_decoded = decode_token(refresh_token)

        # Refresh token should expire later
        assert refresh_decoded["exp"] > access_decoded["exp"]
