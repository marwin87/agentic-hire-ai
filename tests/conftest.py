"""Pytest fixtures for database and integration tests."""

import pytest
import pytest_asyncio
from datetime import datetime, UTC
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from src.db import User, CVFile, CVEmbedding, Job, Evaluation


@pytest_asyncio.fixture
async def db_session() -> AsyncMock:
    """Create a mocked AsyncSession for testing."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest_asyncio.fixture
async def test_user() -> User:
    """Create and return a test user."""
    return User(
        id=uuid4(),
        email="test@example.com",
        password_hash="$2b$12$...",  # placeholder bcrypt hash
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_user_2() -> User:
    """Create and return a second test user for isolation testing."""
    return User(
        id=uuid4(),
        email="test2@example.com",
        password_hash="$2b$12$...",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_cv_file(test_user: User) -> CVFile:
    """Create and return a test CV file."""
    return CVFile(
        id=uuid4(),
        user_id=test_user.id,
        file_path=f"/data/cv/{test_user.id}.pdf",
        file_hash="abc123def456",
        ingested_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_job(test_user: User) -> Job:
    """Create and return a test job."""
    return Job(
        id="job-test-1",
        user_id=test_user.id,
        title="Senior Python Engineer",
        company="Tech Corp",
        description="Looking for experienced Python developer",
        url="https://example.com/job-1",
        salary_range="$150k-$200k",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_job_2(test_user_2: User) -> Job:
    """Create and return a second test job for a different user."""
    return Job(
        id="job-test-2",
        user_id=test_user_2.id,
        title="Data Scientist",
        company="Data Inc",
        description="Machine learning role",
        url="https://example.com/job-2",
        salary_range="$120k-$180k",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_evaluation(test_user: User, test_job: Job) -> Evaluation:
    """Create and return a test evaluation."""
    return Evaluation(
        id=uuid4(),
        user_id=test_user.id,
        job_id=test_job.id,
        match_score=0.85,
        orchestrator_reasoning="Strong match for Python skills",
        tailor_summary="Excellent opportunity",
        evaluated_at=datetime.now(UTC),
    )


@pytest_asyncio.fixture
async def test_cv_embeddings(test_user: User) -> list:
    """Create and return sample CV embeddings for vector search testing."""
    return [
        CVEmbedding(
            id=uuid4(),
            user_id=test_user.id,
            chunk_text="Experienced Python developer with 5 years of FastAPI expertise",
            embedding=[0.1] * 1536,  # Mock embedding vector
            created_at=datetime.now(UTC),
        ),
        CVEmbedding(
            id=uuid4(),
            user_id=test_user.id,
            chunk_text="Skills: Python, FastAPI, PostgreSQL, Docker, Kubernetes",
            embedding=[0.2] * 1536,
            created_at=datetime.now(UTC),
        ),
        CVEmbedding(
            id=uuid4(),
            user_id=test_user.id,
            chunk_text="Led architecture redesign reducing API latency by 40%",
            embedding=[0.15] * 1536,
            created_at=datetime.now(UTC),
        ),
    ]
