"""Tests for db/database.py session management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.database import close_db, get_db, get_session_factory, init_db


@pytest.mark.asyncio
async def test_init_db_creates_engine_and_factory() -> None:
    mock_engine = MagicMock()
    mock_factory = MagicMock()

    with (
        patch("src.db.database.create_async_engine", return_value=mock_engine),
        patch("src.db.database.async_sessionmaker", return_value=mock_factory),
    ):
        from src.config.settings import config

        await init_db(config)

    assert get_session_factory() is mock_factory


@pytest.mark.asyncio
async def test_close_db_disposes_engine() -> None:
    mock_engine = AsyncMock()

    with patch("src.db.database.create_async_engine", return_value=mock_engine):
        from src.config.settings import config

        await init_db(config)

    await close_db()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_close_db_noop_when_engine_is_none() -> None:
    import src.db.database as db_module

    db_module._engine = None
    await close_db()  # should not raise


def test_get_session_factory_raises_when_not_initialized() -> None:
    import src.db.database as db_module

    db_module._session_factory = None
    with pytest.raises(RuntimeError, match="not initialized"):
        get_session_factory()


@pytest.mark.asyncio
async def test_get_db_yields_session() -> None:
    mock_session = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)

    import src.db.database as db_module

    db_module._session_factory = mock_factory

    sessions = []
    async for session in get_db():
        sessions.append(session)

    assert sessions == [mock_session]
