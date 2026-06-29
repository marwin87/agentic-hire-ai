"""Tests for FastAPI dependency injection utilities."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.dependencies import get_config, get_current_user, get_db, get_factory
from src.auth import encode_token
from src.config.settings import config

# ===== simple deps =====


def test_get_config_returns_config_singleton() -> None:
    result = get_config()
    assert result is config


def test_get_factory_returns_agent_factory() -> None:
    with patch("src.api.dependencies.get_agent_factory") as mock_factory:
        mock_factory.return_value = MagicMock()
        result = get_factory()
    assert result is mock_factory.return_value


@pytest.mark.asyncio
async def test_get_db_returns_session() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.api.dependencies.get_session_factory", return_value=mock_factory):
        result = await get_db()

    assert result is mock_session


# ===== get_current_user =====


def _make_credentials(token: str) -> MagicMock:
    creds = MagicMock()
    creds.credentials = token
    return creds


def _make_session_factory(user: object) -> MagicMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    return MagicMock(return_value=mock_session)


@pytest.mark.asyncio
async def test_get_current_user_invalid_token_raises_401() -> None:
    creds = _make_credentials("not.a.valid.jwt")
    with pytest.raises(HTTPException) as exc:
        await get_current_user(credentials=creds)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_missing_user_id_raises_401() -> None:
    token = encode_token(
        {"email": "u@x.com"},  # no user_id
        expires_in_minutes=60,
        token_type="access",
    )
    creds = _make_credentials(token)

    mock_factory = _make_session_factory(None)
    with (
        patch("src.api.dependencies.get_session_factory", return_value=mock_factory),
        pytest.raises(HTTPException) as exc,
    ):
        await get_current_user(credentials=creds)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_user_not_in_db_raises_401() -> None:
    token = encode_token(
        {"user_id": str(uuid4()), "email": "u@x.com"},
        expires_in_minutes=60,
        token_type="access",
    )
    creds = _make_credentials(token)

    mock_factory = _make_session_factory(None)  # no user in DB
    with patch("src.api.dependencies.get_session_factory", return_value=mock_factory):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(credentials=creds)

    assert exc.value.status_code == 401
    assert "not found" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_get_current_user_success_returns_user() -> None:
    user_id = str(uuid4())
    token = encode_token(
        {"user_id": user_id, "email": "u@x.com"},
        expires_in_minutes=60,
        token_type="access",
    )
    creds = _make_credentials(token)

    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "u@x.com"

    mock_factory = _make_session_factory(mock_user)
    with patch("src.api.dependencies.get_session_factory", return_value=mock_factory):
        result = await get_current_user(credentials=creds)

    assert result is mock_user
