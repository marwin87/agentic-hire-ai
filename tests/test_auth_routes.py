"""Tests for auth route handler functions (signup, login, refresh, logout)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.routes.auth import login, logout, refresh, signup
from src.api.schemas import LoginRequest, RefreshRequest, SignupRequest
from src.auth import encode_token


def _mock_db(existing_user: object = None) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_user

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    return db


# ===== signup =====


@pytest.mark.asyncio
async def test_signup_password_mismatch_raises_400() -> None:
    request = SignupRequest(
        email="a@example.com", password="Test123!", password_confirm="Wrong!"
    )
    with pytest.raises(HTTPException) as exc:
        await signup(request, db=_mock_db())
    assert exc.value.status_code == 400
    assert "match" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_signup_weak_password_raises_400() -> None:
    request = SignupRequest(
        email="a@example.com", password="short", password_confirm="short"
    )
    with pytest.raises(HTTPException) as exc:
        await signup(request, db=_mock_db())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_signup_duplicate_email_raises_409() -> None:
    existing = MagicMock()
    existing.email = "a@example.com"
    request = SignupRequest(
        email="a@example.com", password="Test123!", password_confirm="Test123!"
    )
    with pytest.raises(HTTPException) as exc:
        await signup(request, db=_mock_db(existing_user=existing))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_signup_db_error_during_email_check_raises_500() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("connection lost"))
    request = SignupRequest(
        email="a@example.com", password="Secure123!", password_confirm="Secure123!"
    )
    with pytest.raises(HTTPException) as exc:
        await signup(request, db=db)
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_signup_unique_constraint_on_commit_raises_409() -> None:
    db = _mock_db()
    db.commit = AsyncMock(side_effect=Exception("unique constraint violated"))
    request = SignupRequest(
        email="a@example.com", password="Secure123!", password_confirm="Secure123!"
    )
    with patch("src.api.routes.auth.hash_password", return_value="h"):
        with pytest.raises(HTTPException) as exc:
            await signup(request, db=db)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_signup_success_returns_tokens() -> None:
    request = SignupRequest(
        email="new@example.com", password="Secure123!", password_confirm="Secure123!"
    )

    with (
        patch("src.api.routes.auth.hash_password", return_value="hashed_pw"),
        patch("src.api.routes.auth.encode_token", return_value="tok"),
    ):
        result = await signup(request, db=_mock_db())

    assert result["access_token"] == "tok"
    assert result["token_type"] == "bearer"
    assert "expires_in" in result


@pytest.mark.asyncio
async def test_signup_db_insert_error_raises_500() -> None:
    request = SignupRequest(
        email="new@example.com", password="Secure123!", password_confirm="Secure123!"
    )
    db = _mock_db()
    db.commit = AsyncMock(side_effect=Exception("DB write failed"))

    with patch("src.api.routes.auth.hash_password", return_value="hashed_pw"):
        with pytest.raises(HTTPException) as exc:
            await signup(request, db=db)
    assert exc.value.status_code in (500, 409)


# ===== login =====


@pytest.mark.asyncio
async def test_login_user_not_found_raises_401() -> None:
    request = LoginRequest(email="ghost@example.com", password="Pass123!")
    with pytest.raises(HTTPException) as exc:
        await login(request, db=_mock_db(existing_user=None))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_password_raises_401() -> None:
    mock_user = MagicMock()
    mock_user.password_hash = "hashed"

    request = LoginRequest(email="a@example.com", password="WrongPass!")
    with (patch("src.api.routes.auth.verify_password", return_value=False),):
        with pytest.raises(HTTPException) as exc:
            await login(request, db=_mock_db(existing_user=mock_user))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_success_returns_tokens() -> None:
    user_id = uuid4()
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "a@example.com"
    mock_user.password_hash = "hashed"

    request = LoginRequest(email="a@example.com", password="Secure123!")
    with (
        patch("src.api.routes.auth.verify_password", return_value=True),
        patch("src.api.routes.auth.encode_token", return_value="mytoken"),
    ):
        result = await login(request, db=_mock_db(existing_user=mock_user))

    assert result["access_token"] == "mytoken"
    assert result["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_db_error_raises_500() -> None:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=Exception("DB down"))

    request = LoginRequest(email="a@example.com", password="Secure123!")
    with pytest.raises(HTTPException) as exc:
        await login(request, db=db)
    assert exc.value.status_code == 500


# ===== refresh =====


@pytest.mark.asyncio
async def test_refresh_invalid_token_raises_401() -> None:
    request = RefreshRequest(refresh_token="not.a.valid.token")
    with pytest.raises(HTTPException) as exc:
        await refresh(request, db=_mock_db())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_wrong_token_type_raises_401() -> None:
    access_token = encode_token(
        {"user_id": str(uuid4()), "email": "u@x.com"},
        expires_in_minutes=60,
        token_type="access",
    )
    request = RefreshRequest(refresh_token=access_token)
    with pytest.raises(HTTPException) as exc:
        await refresh(request, db=_mock_db())
    assert exc.value.status_code == 401
    assert "not a refresh" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_refresh_success_returns_new_access_token() -> None:
    user_id = str(uuid4())
    token = encode_token(
        {"user_id": user_id, "email": "u@x.com"},
        expires_in_minutes=60 * 24 * 7,
        token_type="refresh",
    )
    request = RefreshRequest(refresh_token=token)
    with patch("src.api.routes.auth.encode_token", return_value="new_access"):
        result = await refresh(request, db=_mock_db())

    assert result["access_token"] == "new_access"
    assert result["refresh_token"] == token
    assert result["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_refresh_missing_user_id_raises_401() -> None:
    token = encode_token(
        {},  # no user_id, no email
        expires_in_minutes=60 * 24 * 7,
        token_type="refresh",
    )
    request = RefreshRequest(refresh_token=token)
    with pytest.raises(HTTPException) as exc:
        await refresh(request, db=_mock_db())
    assert exc.value.status_code == 401


# ===== logout =====


@pytest.mark.asyncio
async def test_logout_returns_success_message() -> None:
    mock_user = MagicMock()
    mock_user.email = "u@x.com"
    result = await logout(user=mock_user)
    assert result["message"] == "Logged out successfully"
