"""Tests for database repositories."""

import pytest
from datetime import datetime, UTC
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories import (
    UserRepository,
    CVFileRepository,
    CVEmbeddingRepository,
    JobRepository,
    EvaluationRepository,
    SearchSessionRepository,
)
from src.db.models import User, CVFile, CVEmbedding, Job, Evaluation, SearchSession


@pytest.mark.asyncio
async def test_user_repository_create() -> None:
    """Test UserRepository.create()."""
    session = AsyncMock(spec=AsyncSession)

    result = await UserRepository.create(
        session, email="test@example.com", password_hash="hashed"
    )

    assert result.email == "test@example.com"
    assert result.password_hash == "hashed"
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_user_repository_get_by_email() -> None:
    """Test UserRepository.get_by_email()."""
    session = AsyncMock(spec=AsyncSession)
    user = User(
        id=uuid4(),
        email="test@example.com",
        password_hash="hashed",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    session.execute.return_value = mock_result

    result = await UserRepository.get_by_email(session, "test@example.com")

    assert result == user
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_cv_file_repository_create() -> None:
    """Test CVFileRepository.create()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = await CVFileRepository.create(
        session,
        user_id=user_id,
        file_path="/data/cv/user.pdf",
        file_hash="hash123",
    )

    assert result.user_id == user_id
    assert result.file_path == "/data/cv/user.pdf"
    assert result.file_hash == "hash123"
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_job_repository_create_or_update_new() -> None:
    """Test JobRepository.create_or_update() for new job."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    job = Job(
        id="job-123",
        user_id=user_id,
        title="Python Engineer",
        company="Tech Corp",
        description="Python role",
        url="https://example.com/job",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    result = await JobRepository.create_or_update(session, job)

    assert result == job
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_job_repository_get_by_user() -> None:
    """Test JobRepository.get_by_user()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    job1 = Job(
        id="job-1",
        user_id=user_id,
        title="Python Engineer",
        company="Tech Corp",
        description="Python role",
        url="https://example.com/job1",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [job1]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await JobRepository.get_by_user(session, user_id)

    assert len(result) == 1
    assert result[0] == job1


@pytest.mark.asyncio
async def test_job_repository_count_by_user() -> None:
    """Test JobRepository.count_by_user()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    jobs = [
        Job(
            id=f"job-{i}",
            user_id=user_id,
            title=f"Job {i}",
            company="Tech Corp",
            url=f"https://example.com/job{i}",
            discovered_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        for i in range(3)
    ]

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = jobs
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await JobRepository.count_by_user(session, user_id)

    assert result == 3


@pytest.mark.asyncio
async def test_evaluation_repository_create() -> None:
    """Test EvaluationRepository.create()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    evaluation = Evaluation(
        id=uuid4(),
        user_id=user_id,
        job_id="job-123",
        match_score=0.85,
        orchestrator_reasoning="Good match",
        evaluated_at=datetime.now(UTC),
    )

    result = await EvaluationRepository.create(session, evaluation)

    assert result == evaluation
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_evaluation_repository_get_by_user() -> None:
    """Test EvaluationRepository.get_by_user()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    evaluation = Evaluation(
        id=uuid4(),
        user_id=user_id,
        job_id="job-123",
        match_score=0.85,
        orchestrator_reasoning="Good match",
        evaluated_at=datetime.now(UTC),
    )

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [evaluation]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await EvaluationRepository.get_by_user(session, user_id)

    assert len(result) == 1
    assert result[0] == evaluation


@pytest.mark.asyncio
async def test_evaluation_repository_update_scores() -> None:
    """Test EvaluationRepository.update_scores()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    evaluation = Evaluation(
        id=uuid4(),
        user_id=user_id,
        job_id="job-123",
        match_score=0.5,
        orchestrator_reasoning="Mediocre",
        evaluated_at=datetime.now(UTC),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = evaluation
    session.execute.return_value = mock_result

    await EvaluationRepository.update_scores(
        session, user_id, "job-123", 0.85, "Good match"
    )

    assert evaluation.match_score == 0.85
    assert evaluation.orchestrator_reasoning == "Good match"
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_cv_embedding_repository_bulk_insert() -> None:
    """Test CVEmbeddingRepository.bulk_insert()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    embeddings = [
        CVEmbedding(
            id=uuid4(),
            user_id=user_id,
            chunk_text="Experienced Python developer",
            embedding=[0.1] * 1536,
            created_at=datetime.now(UTC),
        ),
        CVEmbedding(
            id=uuid4(),
            user_id=user_id,
            chunk_text="Skills: Python, FastAPI, PostgreSQL",
            embedding=[0.2] * 1536,
            created_at=datetime.now(UTC),
        ),
    ]

    await CVEmbeddingRepository.bulk_insert(session, embeddings)

    session.add_all.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_cv_embedding_repository_search_by_user_and_query() -> None:
    """Test CVEmbeddingRepository.search_by_user_and_query()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    embedding1 = CVEmbedding(
        id=uuid4(),
        user_id=user_id,
        chunk_text="Experienced Python developer",
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )

    # Mock pgvector being available
    with patch("src.db.repositories.Vector", create=True):
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [embedding1]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        session.execute.return_value = mock_result

        result = await CVEmbeddingRepository.search_by_user_and_query(
            session, user_id, [0.1] * 1536, limit=5
        )

        assert len(result) == 1
        assert result[0] == embedding1


@pytest.mark.asyncio
async def test_search_session_repository_create() -> None:
    """Test SearchSessionRepository.create()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = await SearchSessionRepository.create(
        session, user_id=user_id, criteria="Python engineer", found_count=5
    )

    assert result.user_id == user_id
    assert result.criteria == "Python engineer"
    assert result.found_count == 5
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_search_session_repository_create_default_count() -> None:
    """Test SearchSessionRepository.create() with default found_count."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()

    result = await SearchSessionRepository.create(
        session, user_id=user_id, criteria="Go engineer"
    )

    assert result.user_id == user_id
    assert result.criteria == "Go engineer"
    assert result.found_count == 0
    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_search_session_repository_get_by_user() -> None:
    """Test SearchSessionRepository.get_by_user()."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    search_session = SearchSession(
        id=uuid4(),
        user_id=user_id,
        criteria="Python engineer",
        found_count=5,
        created_at=datetime.now(UTC),
    )

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [search_session]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await SearchSessionRepository.get_by_user(session, user_id)

    assert len(result) == 1
    assert result[0] == search_session
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_search_session_repository_get_by_user_pagination() -> None:
    """Test SearchSessionRepository.get_by_user() with pagination."""
    session = AsyncMock(spec=AsyncSession)
    user_id = uuid4()
    search_sessions = [
        SearchSession(
            id=uuid4(),
            user_id=user_id,
            criteria=f"Engineer {i}",
            found_count=i,
            created_at=datetime.now(UTC),
        )
        for i in range(5)
    ]

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = search_sessions[1:3]  # Return 2nd and 3rd items
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute.return_value = mock_result

    result = await SearchSessionRepository.get_by_user(
        session, user_id, limit=2, offset=1
    )

    assert len(result) == 2
    session.execute.assert_called_once()
