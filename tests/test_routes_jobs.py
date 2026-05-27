"""Unit tests for GET /jobs endpoint."""

from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_current_user, get_db
from src.api.main import app
from src.db.models import Job, User
from src.db.repositories import JobRepository


@pytest.fixture
def test_user() -> User:
    """Create a test user."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        password_hash="hashed_password",
    )
    return user


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create a mock database session."""
    return AsyncMock()


def test_get_jobs_without_auth_returns_401() -> None:
    """Test endpoint returns 401 when JWT token is missing."""
    client = TestClient(app)
    response = client.get("/api/jobs")
    assert response.status_code == 401


def test_get_jobs_authenticated_returns_200_with_list(
    test_user: User, mock_db: AsyncMock
) -> None:
    """Test successful retrieval of jobs for authenticated user."""
    jobs = [
        Job(
            id="job-1",
            user_id=test_user.id,
            title="Senior Engineer",
            company="TechCorp",
            url="https://example.com/job/1",
            discovered_at=datetime.now(),
        ),
        Job(
            id="job-2",
            user_id=test_user.id,
            title="Developer",
            company="StartupCo",
            url="https://example.com/job/2",
            discovered_at=datetime.now(),
        ),
    ]

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=2
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, None) for job in jobs],
            ):
                client = TestClient(app)
                response = client.get("/api/jobs?page=1&page_size=10")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["total_count"] == 2
        assert data["page_size"] == 10
        assert len(data["jobs"]) == 2
        assert data["jobs"][0]["id"] == "job-1"
        assert data["jobs"][0]["title"] == "Senior Engineer"
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_no_jobs_returns_empty_array(
    test_user: User, mock_db: AsyncMock
) -> None:
    """Test endpoint returns empty array when user has no jobs."""

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=0
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[],
            ):
                client = TestClient(app)
                response = client.get("/api/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["total_count"] == 0
        assert data["jobs"] == []
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_pagination_default_page_1(
    test_user: User, mock_db: AsyncMock
) -> None:
    """Test default pagination page is 1."""
    job = Job(
        id="job-1",
        user_id=test_user.id,
        title="Engineer",
        company="TechCorp",
        url="https://example.com/job/1",
    )

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=1
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, None)],
            ) as mock_get:
                client = TestClient(app)
                response = client.get("/api/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
        # Verify offset was 0 (first page)
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["offset"] == 0
        assert call_kwargs["limit"] == 10
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_pagination_clamp_invalid_page(
    test_user: User, mock_db: AsyncMock
) -> None:
    """Test pagination parameters are clamped to valid range."""
    job = Job(
        id="job-1",
        user_id=test_user.id,
        title="Engineer",
        company="TechCorp",
        url="https://example.com/job/1",
    )

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        # Request page 999 when max is 1
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=1
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, None)],
            ):
                client = TestClient(app)
                response = client.get("/api/jobs?page=999&page_size=10")

        data = response.json()
        assert data["page"] == 1  # Clamped to max page
        assert data["total_count"] == 1
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_match_score_included(test_user: User, mock_db: AsyncMock) -> None:
    """Test match_score is included in response."""
    job = Job(
        id="job-1",
        user_id=test_user.id,
        title="Engineer",
        company="TechCorp",
        url="https://example.com/job/1",
    )

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        # Test with score
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=1
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, 0.85)],
            ):
                client = TestClient(app)
                response = client.get("/api/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data["jobs"][0]["match_score"] == 0.85

        # Test with null score
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=1
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, None)],
            ):
                client = TestClient(app)
                response = client.get("/api/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data["jobs"][0]["match_score"] is None
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_sorted_by_discovered_at_desc(
    test_user: User, mock_db: AsyncMock
) -> None:
    """Test jobs are sorted by discovered_at DESC (newest first)."""
    jobs = [
        Job(
            id="job-1",
            user_id=test_user.id,
            title="Old Position",
            company="Company 1",
            url="https://example.com/job/1",
            discovered_at=datetime(2026, 5, 25),
        ),
        Job(
            id="job-2",
            user_id=test_user.id,
            title="New Position",
            company="Company 2",
            url="https://example.com/job/2",
            discovered_at=datetime(2026, 5, 27),
        ),
    ]

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=2
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(jobs[1], None), (jobs[0], None)],  # Newest first
            ):
                client = TestClient(app)
                response = client.get("/api/jobs")

        data = response.json()
        assert data["jobs"][0]["id"] == "job-2"  # Newest first
        assert data["jobs"][1]["id"] == "job-1"  # Older second
    finally:
        app.dependency_overrides.clear()


def test_get_jobs_user_isolation(test_user: User, mock_db: AsyncMock) -> None:
    """Test user can only see their own jobs via repository user_id filter."""
    job = Job(
        id="job-1",
        user_id=test_user.id,
        title="Job 1",
        company="Company 1",
        url="https://example.com/job/1",
    )

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_db():  # type: ignore
        yield mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch.object(
            JobRepository, "count_by_user", new_callable=AsyncMock, return_value=1
        ):
            with patch.object(
                JobRepository,
                "get_jobs_with_scores",
                new_callable=AsyncMock,
                return_value=[(job, None)],
            ) as mock_get:
                client = TestClient(app)
                response = client.get("/api/jobs")

        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 1

        # Verify the repository was called with the correct user_id
        mock_get.assert_called_once()
        call_user_id = mock_get.call_args[0][1]  # Second positional arg is user_id
        assert call_user_id == test_user.id
    finally:
        app.dependency_overrides.clear()
