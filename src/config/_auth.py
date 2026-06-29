from pydantic import BaseModel, Field, SecretStr


class AuthMixin(BaseModel):
    """JWT token settings and password-policy rules."""

    jwt_secret_key: SecretStr = Field(
        ...,
        description=(
            "Secret key for JWT signing (HS256). Must be set via AGENTIC_HIRE_JWT_SECRET_KEY. "
            "Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        ),
    )
    jwt_algorithm: str = Field("HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        24 * 60, description="Access token lifetime in minutes (default: 24 hours)"
    )
    jwt_refresh_token_expire_days: int = Field(
        30, description="Refresh token lifetime in days"
    )
    password_min_length: int = Field(8, description="Minimum password length")
    password_require_digit: bool = Field(True, description="Require at least one digit")
    password_require_uppercase: bool = Field(
        True, description="Require at least one uppercase letter"
    )
