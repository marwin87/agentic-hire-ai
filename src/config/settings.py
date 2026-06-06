from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from typing import Optional
import secrets


class AppConfig(BaseSettings):
    """
    Application configuration settings.
    Loads environment variables from .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENTIC_HIRE_",  # Optional prefix for env vars
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars not in the model
    )

    # General settings
    debug_mode: bool = Field(
        True, description="Enable debug mode for more verbose logging and features."
    )
    log_level: str = Field(
        "DEBUG", description="Log level: DEBUG, INFO, WARNING, ERROR"
    )
    environment: str = Field(
        "development", description="Runtime environment: development or production"
    )

    # API configuration
    openrouter_base_url: str = Field("https://openrouter.ai/api/v1")
    openrouter_api_key: Optional[SecretStr] = None
    oriosearch_base_url: str = Field("http://localhost:8000")

    # AgenticHire AI specific settings
    max_valid_offers: int = Field(
        3, description="Maximum number of valid job offers to process."
    )
    max_scout_runs: int = Field(
        3, description="Maximum number of iterations for the job scout agent."
    )
    scout_max_iterations: int = Field(
        10, description="Max LLM interaction iterations per scout run."
    )
    scout_rate_limit_delay: float = Field(
        0.5,
        description="Delay (seconds) between scout tool calls to avoid rate limiting.",
    )
    preferred_job_portals: list[str] = Field(
        default=[
            "https://pracuj.pl",
            "https://nofluffjobs.com/pl",
            "https://justjoin.it/",
            "https://linkedin.com",
        ],
        description=(
            "Ordered list of job portals Scout should search first. "
            "Override via AGENTIC_HIRE_PREFERRED_JOB_PORTALS env var as a JSON array."
        ),
    )
    initial_prompt: str = Field(
        "Python Developer or AI Engineer roles. "
        "No Architect, Team Leader or Senior level. "
        "Only consider jobs that are fully remote within Poland or offer hybrid work in Warsaw. "
        "Exclude roles that primarily require Java or non-Python technologies."
    )
    cv_file_path: str = Field(
        "data/cv/sample_cv.pdf", description="Path to the CV file."
    )

    # Database settings
    # Dev-only default — MUST be overridden via AGENTIC_HIRE_DATABASE_URL in non-dev envs.
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire"
        ),
        description="PostgreSQL connection string with asyncpg driver.",
    )
    embedding_dimension: int = Field(
        1536,
        description="Vector embedding dimension for pgvector (default: OpenRouter embeddings).",
    )
    postgres_version: str = Field(
        "17", description="PostgreSQL version (informational)."
    )

    # Job validator settings
    validator_timeout: int = Field(
        10, description="HTTP timeout in seconds for job validation requests."
    )
    validator_content_max_chars: int = Field(
        6000, description="Max characters to analyze for expiration detection."
    )
    validator_max_retries: int = Field(
        2, description="Max retries for failed LLM validation calls."
    )
    validator_cache_enabled: bool = Field(
        True, description="Cache job validation results."
    )

    # LLM settings
    orchestrator_model_name: str = Field("openai/gpt-4o-mini")
    scout_model_name: str = Field("google/gemini-3-flash-preview")
    tailor_model_name: str = Field("openai/gpt-4o-mini")
    vision_model_name: str = Field("openai/gpt-4o")
    validator_model_name: str = Field("openai/gpt-4o")
    embedded_model_name: str = Field("text-embedding-3-small")

    # JWT settings
    jwt_secret_key: SecretStr = Field(
        ...,
        description="Secret key for JWT signing (HS256). Must be set in .env as AGENTIC_HIRE_JWT_SECRET_KEY. Generate with: python -c 'import secrets; print(secrets.token_urlsafe(32))'",
    )
    jwt_algorithm: str = Field("HS256", description="JWT signing algorithm")
    jwt_access_token_expire_minutes: int = Field(
        24 * 60, description="Access token lifetime in minutes (default: 24 hours)"
    )
    jwt_refresh_token_expire_days: int = Field(
        30, description="Refresh token lifetime in days"
    )

    # Password validation settings
    password_min_length: int = Field(8, description="Minimum password length")
    password_require_digit: bool = Field(True, description="Require at least one digit")
    password_require_uppercase: bool = Field(
        True, description="Require at least one uppercase letter"
    )


config = AppConfig()  # type: ignore[call-arg]
