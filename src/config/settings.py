from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator

from src.config._llm import LLMMixin
from src.config._db import DatabaseMixin
from src.config._auth import AuthMixin
from src.config._scraper import ScraperMixin


class AppConfig(LLMMixin, DatabaseMixin, AuthMixin, ScraperMixin, BaseSettings):
    """
    Application configuration. All fields are loaded from the environment
    (prefix: AGENTIC_HIRE_) or a .env file. Fields are grouped in four modules:

      _llm.py    — LLM providers and per-agent model names
      _db.py     — PostgreSQL, pgvector, and RAG chunking
      _auth.py   — JWT tokens and password-policy rules
      _scraper.py — OrioSearch API, web scraper, and job validator
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENTIC_HIRE_",
        case_sensitive=False,
        extra="ignore",
    )

    # General settings
    debug_mode: bool = Field(
        False, description="Enable debug mode for more verbose logging and features."
    )
    log_level: str = Field(
        "DEBUG", description="Log level: DEBUG, INFO, WARNING, ERROR"
    )
    environment: str = Field(
        "development", description="Runtime environment: development or production"
    )

    # Workflow settings
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

    @model_validator(mode="after")
    def reject_dev_credentials_in_production(self) -> "AppConfig":
        if self.environment == "production":
            url_val = self.database_url.get_secret_value()
            if "dev_password" in url_val:
                raise ValueError(
                    "AGENTIC_HIRE_DATABASE_URL must be set explicitly in production. "
                    "The default dev_password credential is not permitted outside development."
                )
        return self


config = AppConfig()  # type: ignore[call-arg]
