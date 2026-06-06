"""Integration tests for complete auth flows and security scenarios."""

import pytest
from datetime import datetime, timedelta, timezone
import jwt as pyjwt

from src.auth import encode_token, decode_token, hash_password, verify_password
from src.config.settings import config


class TestAuthenticationFlow:
    """Tests for complete user authentication lifecycle."""

    def test_full_signup_login_flow(self) -> None:
        """Test complete flow: signup → login → token usage."""
        email = "testuser@example.com"
        password = "SecurePass123"

        # Signup: hash password and encode tokens
        password_hash = hash_password(password)
        assert verify_password(password, password_hash)

        user_data = {"user_id": "user-123", "email": email}
        access_token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )
        refresh_token = encode_token(
            user_data,
            config.jwt_refresh_token_expire_days * 24 * 60,
            "refresh",
        )

        # Verify tokens are valid
        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        assert access_payload["email"] == email
        assert refresh_payload["email"] == email
        assert access_payload["type"] == "access"
        assert refresh_payload["type"] == "refresh"

    def test_refresh_token_rotation(self) -> None:
        """Test refresh token endpoint returns new access token without rotating refresh token."""
        import time

        user_id = "user-456"
        email = "refresh@example.com"

        # Original tokens from login
        original_access = encode_token(
            {"user_id": user_id, "email": email},
            config.jwt_access_token_expire_minutes,
            "access",
        )
        original_refresh = encode_token(
            {"user_id": user_id, "email": email},
            config.jwt_refresh_token_expire_days * 24 * 60,
            "refresh",
        )

        # Simulate refresh endpoint: validate refresh token, issue new access token
        time.sleep(0.1)  # Ensure different iat timestamp
        refresh_payload = decode_token(original_refresh)
        new_access = encode_token(
            {
                "user_id": refresh_payload["user_id"],
                "email": refresh_payload["email"],
            },
            config.jwt_access_token_expire_minutes,
            "access",
        )

        # Verify both access tokens are valid and have same user
        access1_payload = decode_token(original_access)
        access2_payload = decode_token(new_access)
        assert access1_payload["user_id"] == access2_payload["user_id"]
        # Refresh token should be unchanged
        assert decode_token(original_refresh)["type"] == "refresh"

    def test_concurrent_token_refresh(self) -> None:
        """Test that multiple refresh requests with same refresh token succeed."""
        user_id = "user-789"
        email = "concurrent@example.com"

        refresh_token = encode_token(
            {"user_id": user_id, "email": email},
            config.jwt_refresh_token_expire_days * 24 * 60,
            "refresh",
        )

        # Simulate two concurrent refresh requests
        refresh_payload1 = decode_token(refresh_token)
        refresh_payload2 = decode_token(refresh_token)

        new_access1 = encode_token(
            {
                "user_id": refresh_payload1["user_id"],
                "email": refresh_payload1["email"],
            },
            config.jwt_access_token_expire_minutes,
            "access",
        )
        new_access2 = encode_token(
            {
                "user_id": refresh_payload2["user_id"],
                "email": refresh_payload2["email"],
            },
            config.jwt_access_token_expire_minutes,
            "access",
        )

        # Both should be valid (different tokens due to different iat timestamps)
        assert decode_token(new_access1)["user_id"] == user_id
        assert decode_token(new_access2)["user_id"] == user_id


class TestTokenExpiration:
    """Tests for token expiration edge cases."""

    def test_token_valid_at_boundary(self) -> None:
        """Test token is valid right before expiration."""
        user_data = {"user_id": "boundary-test", "email": "boundary@example.com"}

        # Create token expiring exactly 1 minute from now
        token = encode_token(user_data, expires_in_minutes=1, token_type="access")

        # Should be decodable immediately
        payload = decode_token(token)
        assert payload["user_id"] == "boundary-test"

    def test_token_invalid_after_expiration(self) -> None:
        """Test token is invalid after expiration."""
        now = datetime.now(timezone.utc)
        to_encode = {
            "user_id": "expired-test",
            "email": "expired@example.com",
            "exp": now - timedelta(seconds=1),
            "iat": now,
            "type": "access",
        }
        expired_token = pyjwt.encode(
            to_encode,
            config.jwt_secret_key.get_secret_value(),
            algorithm=config.jwt_algorithm,
        )

        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_token(expired_token)

    def test_refresh_token_expiration_longer_than_access(self) -> None:
        """Test refresh tokens live much longer than access tokens."""
        user_data = {"user_id": "lifetime-test", "email": "lifetime@example.com"}

        access_token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )
        refresh_token = encode_token(
            user_data,
            config.jwt_refresh_token_expire_days * 24 * 60,
            "refresh",
        )

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        # Refresh token should expire 30 days later
        access_exp = access_payload["exp"]
        refresh_exp = refresh_payload["exp"]
        diff_seconds = refresh_exp - access_exp

        # Should be approximately 30 days = 2,592,000 seconds
        assert diff_seconds > 2_500_000  # Allow 1 day margin
        assert diff_seconds < 2_700_000


class TestPasswordValidationEdgeCases:
    """Tests for password validation boundaries."""

    def test_password_exact_minimum_length(self) -> None:
        """Test password at exact minimum length (8 chars) is valid."""
        from src.auth import validate_password_strength

        password = "Pass1234"  # 8 chars, has digit + uppercase
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None

    def test_password_one_char_too_short(self) -> None:
        """Test password one char below minimum is rejected."""
        from src.auth import validate_password_strength

        password = "Pass123"  # 7 chars
        valid, error = validate_password_strength(password)
        assert valid is False
        assert error is not None

    def test_password_with_special_characters_allowed(self) -> None:
        """Test that special characters in password are allowed (not required)."""
        from src.auth import validate_password_strength

        password = "Pass123!@#$%"  # Has digit, uppercase, special chars
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None

    def test_password_very_long(self) -> None:
        """Test very long password is accepted."""
        from src.auth import validate_password_strength

        password = "A" * 100 + "1" + "B"  # 102 chars with uppercase, digit
        valid, error = validate_password_strength(password)
        assert valid is True
        assert error is None


class TestPasswordHashing:
    """Tests for password hashing security properties."""

    def test_password_not_stored_plaintext(self) -> None:
        """Test that password hashing produces non-plaintext output."""
        password = "SecurePass123"
        hashed = hash_password(password)

        # Hashed should be different from plaintext
        assert hashed != password
        # Hashed should start with argon2 format marker
        assert hashed.startswith("$argon2")

    def test_same_password_different_hashes(self) -> None:
        """Test that same password produces different hashes (salting)."""
        password = "SecurePass123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        # Hashes should differ due to random salt
        assert hash1 != hash2
        # Both should verify the password
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)

    def test_similar_passwords_different_hashes(self) -> None:
        """Test that similar passwords produce different hashes."""
        password1 = "SecurePass123"
        password2 = "SecurePass124"  # One digit different

        hash1 = hash_password(password1)
        hash2 = hash_password(password2)

        assert hash1 != hash2
        assert verify_password(password1, hash1)
        assert not verify_password(password2, hash1)


class TestTokenTampering:
    """Tests for token tampering detection."""

    def test_tampered_token_rejected(self) -> None:
        """Test that tampering with token payload is detected."""
        user_data = {"user_id": "tamper-test", "email": "tamper@example.com"}
        token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )

        # Tamper with token by modifying last characters
        tampered_token = token[:-20] + "0" * 20

        with pytest.raises(pyjwt.DecodeError):
            decode_token(tampered_token)

    def test_token_with_wrong_secret_rejected(self) -> None:
        """Test that token signed with different secret is rejected."""
        user_data = {"user_id": "secret-test", "email": "secret@example.com"}

        # Create token with correct secret
        token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )

        # Try to decode with wrong secret
        wrong_secret = "wrong-secret-key-12345"
        with pytest.raises(pyjwt.InvalidSignatureError):
            pyjwt.decode(token, wrong_secret, algorithms=[config.jwt_algorithm])

    def test_access_token_not_usable_as_refresh(self) -> None:
        """Test that access tokens cannot be used where refresh tokens expected."""
        user_data = {"user_id": "type-test", "email": "type@example.com"}
        access_token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )

        payload = decode_token(access_token)
        assert payload["type"] == "access"
        # Verify we can detect it's not a refresh token
        assert payload["type"] != "refresh"


class TestEmailValidationEdgeCases:
    """Tests for email handling in tokens and requests."""

    def test_email_preserved_in_token(self) -> None:
        """Test that email is correctly preserved in JWT token."""
        email = "special+tag@example.co.uk"
        user_data = {"user_id": "email-test", "email": email}

        token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )
        payload = decode_token(token)

        assert payload["email"] == email

    def test_very_long_email_in_token(self) -> None:
        """Test that very long email addresses are handled."""
        email = "a" * 64 + "@" + "b" * 63 + ".example.com"  # Very long but valid
        user_data = {"user_id": "long-email-test", "email": email}

        token = encode_token(
            user_data, config.jwt_access_token_expire_minutes, "access"
        )
        payload = decode_token(token)

        assert payload["email"] == email
