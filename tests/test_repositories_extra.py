"""Tests for repository methods not covered by test_repositories.py."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.db.models import CVEmbedding, CVFile, Evaluation, Job, User
from src.db.repositories import (
    CVEmbeddingRepository,
    CVFileRepository,
    EvaluationRepository,
    JobRepository,
    UserRepository,
)


def _session(scalar_result: object = None, scalars_list: list = None) -> AsyncMock:
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = scalar_result
    if scalars_list is not None:
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = scalars_list
        mock_result.scalars.return_value = mock_scalars
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


# ===== UserRepository =====


@pytest.mark.asyncio
async def test_user_repository_get_by_id_found() -> None:
    user = User(id=uuid4(), email="u@x.com", password_hash="h")
    session = _session(scalar_result=user)
    result = await UserRepository.get_by_id(session, user.id)
    assert result is user


@pytest.mark.asyncio
async def test_user_repository_get_by_id_not_found() -> None:
    session = _session(scalar_result=None)
    result = await UserRepository.get_by_id(session, uuid4())
    assert result is None


# ===== CVFileRepository =====


@pytest.mark.asyncio
async def test_cv_file_repository_get_latest_by_user_found() -> None:
    cv = CVFile(user_id=uuid4(), file_path="/cv.pdf", file_hash="abc")
    session = _session(scalar_result=cv)
    result = await CVFileRepository.get_latest_by_user(session, uuid4())
    assert result is cv


@pytest.mark.asyncio
async def test_cv_file_repository_get_latest_by_user_none() -> None:
    session = _session(scalar_result=None)
    result = await CVFileRepository.get_latest_by_user(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_cv_file_repository_update_hash_when_found() -> None:
    cv = CVFile(user_id=uuid4(), file_path="/cv.pdf", file_hash="old")
    session = _session(scalar_result=cv)
    await CVFileRepository.update_hash(session, cv.user_id, "new_hash")  # type: ignore[arg-type]
    assert cv.file_hash == "new_hash"


@pytest.mark.asyncio
async def test_cv_file_repository_update_hash_when_not_found() -> None:
    session = _session(scalar_result=None)
    await CVFileRepository.update_hash(session, uuid4(), "new_hash")  # no-op, no raise


# ===== CVEmbeddingRepository =====


@pytest.mark.asyncio
async def test_cv_embedding_search_returns_empty_when_vector_is_none() -> None:
    session = AsyncMock()
    with patch("src.db.repositories.Vector", None):
        result = await CVEmbeddingRepository.search_by_user_and_query(
            session, uuid4(), [0.1] * 10
        )
    assert result == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_cv_embedding_delete_by_user_removes_all() -> None:
    uid = uuid4()
    emb1 = CVEmbedding(id=uuid4(), user_id=uid, chunk_text="a", embedding=[0.1])
    emb2 = CVEmbedding(id=uuid4(), user_id=uid, chunk_text="b", embedding=[0.2])
    session = _session(scalars_list=[emb1, emb2])
    await CVEmbeddingRepository.delete_by_user(session, uid)
    assert session.delete.call_count == 2
    session.flush.assert_called_once()


# ===== JobRepository =====


@pytest.mark.asyncio
async def test_job_repository_create_or_update_existing_same_user() -> None:
    uid = uuid4()
    existing = Job(id="j1", user_id=uid, title="Old", company="C", url="http://x.com")
    new_job = Job(id="j1", user_id=uid, title="New", company="C2", url="http://y.com")
    session = _session(scalar_result=existing)
    result = await JobRepository.create_or_update(session, new_job)
    assert result.title == "New"
    assert result.url == "http://y.com"
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_job_repository_create_or_update_existing_different_user() -> None:
    uid1, uid2 = uuid4(), uuid4()
    existing = Job(id="j1", user_id=uid1, title="Job", company="C", url="http://x.com")
    new_job = Job(id="j1", user_id=uid2, title="Job", company="C", url="http://x.com")
    session = _session(scalar_result=existing)
    result = await JobRepository.create_or_update(session, new_job)
    assert result is existing
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_job_repository_get_by_id_found() -> None:
    uid = uuid4()
    job = Job(id="j1", user_id=uid, title="Dev", company="C", url="http://x.com")
    session = _session(scalar_result=job)
    result = await JobRepository.get_by_id(session, "j1", uid)
    assert result is job


@pytest.mark.asyncio
async def test_job_repository_get_by_id_not_found() -> None:
    session = _session(scalar_result=None)
    result = await JobRepository.get_by_id(session, "missing", uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_job_repository_get_jobs_with_scores_returns_tuples() -> None:
    uid = uuid4()
    job = Job(id="j1", user_id=uid, title="Dev", company="C", url="http://x.com")
    eval_ = MagicMock()
    eval_.match_score = 0.9

    mock_result = MagicMock()
    mock_result.all.return_value = [(job, eval_), (job, None)]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=mock_result)

    result = await JobRepository.get_jobs_with_scores(session, uid)
    assert result[0] == (job, 0.9)
    assert result[1] == (job, None)


@pytest.mark.asyncio
async def test_job_repository_delete_by_id_found() -> None:
    uid = uuid4()
    job = Job(id="j1", user_id=uid, title="Dev", company="C", url="http://x.com")
    session = _session(scalar_result=job)
    result = await JobRepository.delete_by_id(session, "j1", uid)
    assert result is True
    session.delete.assert_called_once_with(job)
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_job_repository_delete_by_id_not_found() -> None:
    session = _session(scalar_result=None)
    result = await JobRepository.delete_by_id(session, "missing", uuid4())
    assert result is False
    session.delete.assert_not_called()


@pytest.mark.asyncio
async def test_job_repository_delete_all_by_user() -> None:
    uid = uuid4()
    jobs = [
        Job(id=f"j{i}", user_id=uid, title=f"Job {i}", company="C", url="http://x.com")
        for i in range(3)
    ]
    session = _session(scalars_list=jobs)
    count = await JobRepository.delete_all_by_user(session, uid)
    assert count == 3
    assert session.delete.call_count == 3


# ===== EvaluationRepository =====


@pytest.mark.asyncio
async def test_evaluation_repository_get_by_job_id_found() -> None:
    uid = uuid4()
    ev = Evaluation(id=uuid4(), user_id=uid, job_id="j1", match_score=0.8)
    session = _session(scalar_result=ev)
    result = await EvaluationRepository.get_by_job_id(session, "j1", uid)
    assert result is ev


@pytest.mark.asyncio
async def test_evaluation_repository_get_by_job_id_not_found() -> None:
    session = _session(scalar_result=None)
    result = await EvaluationRepository.get_by_job_id(session, "missing", uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_evaluation_repository_update_scores_noop_when_not_found() -> None:
    session = _session(scalar_result=None)
    await EvaluationRepository.update_scores(session, uuid4(), "j1", 0.9, "Great")
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_repository_upsert_executes_statement() -> None:
    session = AsyncMock()
    session.execute = AsyncMock()
    uid = uuid4()
    await EvaluationRepository.upsert(
        session, uid, "j1", 0.85, "Good match", "Strong candidate"
    )
    session.execute.assert_called_once()
