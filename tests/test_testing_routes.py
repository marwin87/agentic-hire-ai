"""Tests for internal test-support route handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.routes.testing import (
    _require_debug,
    _resolve_user,
    delete_test_user,
    seed_test_cv_file,
    seed_test_job,
)


class TestEmailBody:
    email: str

    def __init__(self, email: str) -> None:
        self.email = email


def _mock_db(user: object = None) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


# ===== _require_debug =====


def test_require_debug_raises_404_when_debug_false() -> None:
    with patch("src.api.routes.testing.config") as mock_cfg:
        mock_cfg.debug_mode = False
        with pytest.raises(HTTPException) as exc:
            _require_debug()
    assert exc.value.status_code == 404


def test_require_debug_passes_when_debug_true() -> None:
    with patch("src.api.routes.testing.config") as mock_cfg:
        mock_cfg.debug_mode = True
        _require_debug()  # should not raise


# ===== _resolve_user =====


@pytest.mark.asyncio
async def test_resolve_user_raises_404_when_not_found() -> None:
    db = _mock_db(user=None)
    with pytest.raises(HTTPException) as exc:
        await _resolve_user("ghost@example.com", db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_user_returns_user_when_found() -> None:
    mock_user = MagicMock()
    mock_user.email = "found@example.com"
    db = _mock_db(user=mock_user)
    result = await _resolve_user("found@example.com", db)
    assert result is mock_user


# ===== delete_test_user =====


@pytest.mark.asyncio
async def test_delete_test_user_executes_delete_and_commits() -> None:
    db = _mock_db()
    body = TestEmailBody("user@example.com")
    await delete_test_user(body=body, db=db, _=None)  # type: ignore[arg-type]
    db.execute.assert_called_once()
    db.commit.assert_called_once()


# ===== seed_test_job =====


@pytest.mark.asyncio
async def test_seed_test_job_adds_job_and_commits() -> None:
    mock_user = MagicMock()
    mock_user.id = uuid4()
    db = _mock_db(user=mock_user)
    body = TestEmailBody("user@example.com")
    await seed_test_job(body=body, db=db, _=None)  # type: ignore[arg-type]
    db.add.assert_called_once()
    db.commit.assert_called_once()


# ===== seed_test_cv_file =====


@pytest.mark.asyncio
async def test_seed_test_cv_file_adds_cv_and_commits() -> None:
    mock_user = MagicMock()
    mock_user.id = uuid4()
    db = _mock_db(user=mock_user)
    body = TestEmailBody("user@example.com")
    await seed_test_cv_file(body=body, db=db, _=None)  # type: ignore[arg-type]
    db.add.assert_called_once()
    db.commit.assert_called_once()
