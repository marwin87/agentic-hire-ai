"""Tests for delete_job and delete_all_jobs handlers + get_jobs error path."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException

from src.api.routes.jobs import delete_all_jobs, delete_job, get_jobs
from src.db.repositories import JobRepository


def _user() -> MagicMock:
    u = MagicMock()
    u.id = uuid4()
    u.email = "u@x.com"
    return u


@pytest.mark.asyncio
async def test_get_jobs_db_error_raises_503() -> None:
    session = AsyncMock()
    with patch.object(JobRepository, "count_by_user", side_effect=Exception("DB down")):
        with pytest.raises(HTTPException) as exc:
            await get_jobs(page=1, page_size=10, user=_user(), session=session)
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_delete_job_not_found_raises_404() -> None:
    session = AsyncMock()
    session.commit = AsyncMock()
    with patch.object(
        JobRepository, "delete_by_id", new_callable=AsyncMock, return_value=False
    ):
        with pytest.raises(HTTPException) as exc:
            await delete_job(job_id="missing", user=_user(), session=session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_job_success_commits() -> None:
    session = AsyncMock()
    session.commit = AsyncMock()
    with patch.object(
        JobRepository, "delete_by_id", new_callable=AsyncMock, return_value=True
    ):
        await delete_job(job_id="j1", user=_user(), session=session)
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_delete_all_jobs_returns_count() -> None:
    session = AsyncMock()
    session.commit = AsyncMock()
    with patch.object(
        JobRepository, "delete_all_by_user", new_callable=AsyncMock, return_value=5
    ):
        result = await delete_all_jobs(user=_user(), session=session)
    assert result == {"deleted": 5}
    session.commit.assert_called_once()
