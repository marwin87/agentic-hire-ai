"""Tests for database engine configuration helpers."""

from unittest.mock import MagicMock, patch

from sqlalchemy.pool import NullPool, QueuePool

from src.db.config import configure_engine, get_pool_class


def test_get_pool_class_test_env() -> None:
    assert get_pool_class("test") is NullPool


def test_get_pool_class_production() -> None:
    assert get_pool_class("production") is QueuePool


def test_get_pool_class_development() -> None:
    assert get_pool_class("development") is QueuePool


def test_get_pool_class_staging() -> None:
    assert get_pool_class("staging") is QueuePool


@patch("src.db.config.create_async_engine")
def test_configure_engine_production_uses_queue_pool(mock_create: MagicMock) -> None:
    mock_create.return_value = MagicMock()
    configure_engine("postgresql+asyncpg://u:p@localhost/db", environment="production")
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["poolclass"] is QueuePool
    assert "pool_size" in call_kwargs
    assert "max_overflow" in call_kwargs


@patch("src.db.config.create_async_engine")
def test_configure_engine_test_uses_null_pool(mock_create: MagicMock) -> None:
    mock_create.return_value = MagicMock()
    configure_engine("postgresql+asyncpg://u:p@localhost/db", environment="test")
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["poolclass"] is NullPool
    assert "pool_size" not in call_kwargs
    assert call_kwargs.get("connect_args", {}).get("check_same_thread") is False


@patch("src.db.config.create_async_engine")
def test_configure_engine_echo_flag(mock_create: MagicMock) -> None:
    mock_create.return_value = MagicMock()
    configure_engine("postgresql+asyncpg://u:p@localhost/db", echo=True)
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["echo"] is True


@patch("src.db.config.create_async_engine")
def test_configure_engine_passes_url_as_first_arg(mock_create: MagicMock) -> None:
    mock_create.return_value = MagicMock()
    url = "postgresql+asyncpg://u:p@localhost/testdb"
    configure_engine(url)
    assert mock_create.call_args.args[0] == url


@patch("src.db.config.create_async_engine")
def test_configure_engine_pool_pre_ping_enabled(mock_create: MagicMock) -> None:
    mock_create.return_value = MagicMock()
    configure_engine("postgresql+asyncpg://u:p@localhost/db")
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["pool_pre_ping"] is True
