"""Tests for FastAPI dependency injection utilities."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.dependencies import get_current_user, get_db
from src.auth import encode_token

# ===== simple deps =====


@pytest.mark.asyncio
async def test_get_db_returns_session() -> None:
    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=mock_ctx)

    with patch("src.db.database.get_session_factory", return_value=mock_factory):
        sessions = [s async for s in get_db()]

    assert len(sessions) == 1
    assert sessions[0] is mock_session


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
