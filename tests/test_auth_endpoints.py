"""Tests for auth endpoint request/response schemas and basic validation."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from src.auth import hash_password, encode_token, decode_token
from src.config.settings import config
from src.api.schemas import SignupRequest, LoginRequest, RefreshRequest, TokenResponse


class TestSignupRequestValidation:
    """Tests for SignupRequest schema validation."""

    def test_signup_request_valid(self) -> None:
        """Test that valid signup request passes validation."""
        request = SignupRequest(
            email="user@example.com",
            password="SecurePass123",
            password_confirm="SecurePass123",
        )
        assert request.email == "user@example.com"
        assert request.password == "SecurePass123"
        assert request.password_confirm == "SecurePass123"

    def test_signup_request_missing_email(self) -> None:
        """Test that signup request without email fails validation."""
        with pytest.raises(ValidationError):
            SignupRequest(  # type: ignore[call-arg]
                password="SecurePass123",
                password_confirm="SecurePass123",
            )

    def test_signup_request_missing_password(self) -> None:
        """Test that signup request without password fails validation."""
        with pytest.raises(ValidationError):
            SignupRequest(  # type: ignore[call-arg]
                email="user@example.com",
                password_confirm="SecurePass123",
            )

    def test_signup_request_missing_password_confirm(self) -> None:
        """Test that signup request without password_confirm fails validation."""
        with pytest.raises(ValidationError):
            SignupRequest(  # type: ignore[call-arg]
                email="user@example.com",
                password="SecurePass123",
            )


class TestLoginRequestValidation:
    """Tests for LoginRequest schema validation."""

    def test_login_request_valid(self) -> None:
        """Test that valid login request passes validation."""
        request = LoginRequest(
            email="user@example.com",
            password="SecurePass123",
        )
        assert request.email == "user@example.com"
        assert request.password == "SecurePass123"

    def test_login_request_missing_email(self) -> None:
        """Test that login request without email fails validation."""
        with pytest.raises(ValidationError):
            LoginRequest(password="SecurePass123")  # type: ignore[call-arg]

    def test_login_request_missing_password(self) -> None:
        """Test that login request without password fails validation."""
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com")  # type: ignore[call-arg]


class TestRefreshRequestValidation:
    """Tests for RefreshRequest schema validation."""

    def test_refresh_request_valid(self) -> None:
        """Test that valid refresh request passes validation."""
        user_id = str(uuid4())
        email = "user@example.com"
        refresh_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_refresh_token_expire_days * 24 * 60,
            token_type="refresh",
        )

        request = RefreshRequest(refresh_token=refresh_token)
        assert request.refresh_token == refresh_token

    def test_refresh_request_missing_token(self) -> None:
        """Test that refresh request without token fails validation."""
        with pytest.raises(ValidationError):
            RefreshRequest()  # type: ignore[call-arg]


class TestTokenResponseValidation:
    """Tests for TokenResponse schema validation."""

    def test_token_response_valid(self) -> None:
        """Test that valid token response passes validation."""
        response = TokenResponse(
            access_token="access.token.here",
            refresh_token="refresh.token.here",
            token_type="bearer",
            expires_in=3600,
        )
        assert response.access_token == "access.token.here"
        assert response.refresh_token == "refresh.token.here"
        assert response.token_type == "bearer"
        assert response.expires_in == 3600

    def test_token_response_no_refresh_token(self) -> None:
        """Test that token response without refresh token is valid (for refresh endpoint)."""
        response = TokenResponse(  # type: ignore[call-arg]
            access_token="access.token.here",
            token_type="bearer",
            expires_in=3600,
        )
        assert response.access_token == "access.token.here"
        assert response.refresh_token is None
        assert response.token_type == "bearer"

    def test_token_response_missing_access_token(self) -> None:
        """Test that token response without access token fails validation."""
        with pytest.raises(ValidationError):
            TokenResponse(  # type: ignore[call-arg]
                refresh_token="refresh.token.here",
                token_type="bearer",
                expires_in=3600,
            )

    def test_token_response_missing_token_type(self) -> None:
        """Test that token response without token type fails validation."""
        with pytest.raises(ValidationError):
            TokenResponse(  # type: ignore[call-arg]
                access_token="access.token.here",
                refresh_token="refresh.token.here",
                expires_in=3600,
            )

    def test_token_response_missing_expires_in(self) -> None:
        """Test that token response without expires_in fails validation."""
        with pytest.raises(ValidationError):
            TokenResponse(  # type: ignore[call-arg]
                access_token="access.token.here",
                refresh_token="refresh.token.here",
                token_type="bearer",
            )


class TestAuthTokenGeneration:
    """Integration tests for token generation in auth flow."""

    def test_access_token_structure(self) -> None:
        """Test that generated access token has correct structure and claims."""
        import jwt as pyjwt

        user_id = str(uuid4())
        email = "test@example.com"

        access_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_access_token_expire_minutes,
            token_type="access",
        )

        # Verify token is a valid JWT
        decoded = decode_token(access_token)

        assert decoded["user_id"] == user_id
        assert decoded["email"] == email
        assert decoded["type"] == "access"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_refresh_token_structure(self) -> None:
        """Test that generated refresh token has correct structure and claims."""
        user_id = str(uuid4())
        email = "test@example.com"

        refresh_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_refresh_token_expire_days * 24 * 60,
            token_type="refresh",
        )

        # Verify token is a valid JWT
        decoded = decode_token(refresh_token)

        assert decoded["user_id"] == user_id
        assert decoded["email"] == email
        assert decoded["type"] == "refresh"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_access_token_expiration(self) -> None:
        """Test that access token expires at configured time."""
        user_id = str(uuid4())
        email = "test@example.com"

        before_encode = datetime.now(timezone.utc)
        access_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_access_token_expire_minutes,
            token_type="access",
        )
        after_encode = datetime.now(timezone.utc)

        decoded = decode_token(access_token)
        exp_datetime = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)

        # Token should expire in approximately jwt_access_token_expire_minutes
        expected_min = before_encode + timedelta(minutes=config.jwt_access_token_expire_minutes - 1)
        expected_max = after_encode + timedelta(minutes=config.jwt_access_token_expire_minutes + 1)

        assert expected_min <= exp_datetime <= expected_max

    def test_refresh_token_longer_lifetime(self) -> None:
        """Test that refresh token lives longer than access token."""
        user_id = str(uuid4())
        email = "test@example.com"

        access_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_access_token_expire_minutes,
            token_type="access",
        )
        refresh_token = encode_token(
            {"user_id": user_id, "email": email},
            expires_in_minutes=config.jwt_refresh_token_expire_days * 24 * 60,
            token_type="refresh",
        )

        access_decoded = decode_token(access_token)
        refresh_decoded = decode_token(refresh_token)

        # Refresh token should expire much later than access token
        assert refresh_decoded["exp"] > access_decoded["exp"]


class TestAuthPasswordHashing:
    """Tests for password hashing in auth context."""

    def test_password_hashing_integration(self) -> None:
        """Test password hashing as used in signup."""
        from src.auth import verify_password

        password = "SecurePass123"
        hashed = hash_password(password)

        # Verify the hashed password works
        assert verify_password(password, hashed)

    def test_different_passwords_rejected(self) -> None:
        """Test that different passwords are rejected."""
        from src.auth import verify_password

        password = "SecurePass123"
        hashed = hash_password(password)

        wrong_password = "WrongPass456"
        assert not verify_password(wrong_password, hashed)
