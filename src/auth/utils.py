"""JWT and password utilities for authentication."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import re

import jwt
from passlib.context import CryptContext  # type: ignore[import-untyped]

from src.config.settings import config

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2.

    Args:
        password: Plaintext password to hash

    Returns:
        Argon2 hashed password (can be stored in database)
    """
    return pwd_context.hash(password)  # type: ignore[no-any-return]


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against an Argon2 hash.

    Args:
        plain: Plaintext password to verify
        hashed: Argon2 hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain, hashed)  # type: ignore[no-any-return]


def encode_token(
    data: dict[str, Any],
    expires_in_minutes: int,
    token_type: str = "access",
) -> str:
    """Encode a JWT token with claims and expiration.

    Args:
        data: Dictionary of claims to encode (e.g., {"user_id": "...", "email": "..."})
        expires_in_minutes: Token lifetime in minutes
        token_type: Token type for identification ("access" or "refresh")

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_in_minutes)

    to_encode.update(
        {
            "exp": expire,
            "iat": now,
            "type": token_type,
        }
    )

    encoded_jwt = jwt.encode(
        to_encode,
        config.jwt_secret_key.get_secret_value(),
        algorithm=config.jwt_algorithm,
    )

    return encoded_jwt


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token.

    Args:
        token: JWT token string to decode

    Returns:
        Dictionary of decoded claims

    Raises:
        jwt.InvalidTokenError: If token is invalid, expired, or malformed
    """
    payload = jwt.decode(
        token,
        config.jwt_secret_key.get_secret_value(),
        algorithms=[config.jwt_algorithm],
    )
    return payload


def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
    """Validate password strength based on configured rules.

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid: bool, error_message: Optional[str])
        If valid, returns (True, None)
        If invalid, returns (False, "error description")
    """
    if len(password) < config.password_min_length:
        return (
            False,
            f"Password must be at least {config.password_min_length} characters long",
        )

    if config.password_require_digit and not re.search(r"\d", password):
        return False, "Password must contain at least one digit"

    if config.password_require_uppercase and not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"

    return True, None
