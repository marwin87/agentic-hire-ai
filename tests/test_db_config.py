"""Tests for database configuration."""

import pytest
from src.config.settings import AppConfig


def test_database_url_configured() -> None:
    """Test that database URL is properly configured."""
    config = AppConfig()
    assert config.database_url
    assert (
        "postgresql" in config.database_url.get_secret_value()
        or "asyncpg" in config.database_url.get_secret_value()
    )


def test_embedding_dimension_configured() -> None:
    """Test that embedding dimension is configured."""
    config = AppConfig()
    assert config.embedding_dimension == 1536


def test_postgres_version_configured() -> None:
    """Test that PostgreSQL version is configured."""
    config = AppConfig()
    assert config.postgres_version == "17"
