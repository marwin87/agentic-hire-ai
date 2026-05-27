"""Integration tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, AsyncMock, patch
from src.api.main import app
from src.schema.state import JobOffer


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """Test that /health endpoint responds correctly."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Scout Endpoint Tests (Phase 3)


@patch("src.api.routes.search.AgentFactory")
@patch("src.api.routes.search.get_cv_context_async")
@patch("src.api.routes.search.JobRepository.create_or_update")
@patch("src.api.routes.search.SearchSessionRepository.create")
def test_scout_endpoint_authenticated(
    mock_create_session: AsyncMock,
    mock_create_job: AsyncMock,
    mock_get_cv_context: AsyncMock,
    mock_agent_factory: MagicMock,
    client: TestClient,
) -> None:
    """Test POST /scout with valid JWT, found jobs, and database persistence."""
    from uuid import uuid4
    from src.api.dependencies import get_current_user, get_db

    user_id = uuid4()

    # Mock authenticated user
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "test@example.com"

    def mock_get_current_user_override() -> MagicMock:
        return mock_user

    # Mock database session
    mock_session = AsyncMock()

    async def mock_get_db_override() -> AsyncMock:
        return mock_session

    # Override the dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user_override
    app.dependency_overrides[get_db] = mock_get_db_override

    try:
        # Mock CV context retrieval
        mock_get_cv_context.return_value = "Python developer with 10 years experience"

        # Mock factory and scout agent
        mock_factory = MagicMock()
        mock_agent_factory.return_value = mock_factory

        job1 = JobOffer(
            id="job-1",
            title="Senior Python Engineer",
            company="TechCorp",
            salary_range="$150k-200k",
            description="Python role",
            url="http://example.com/job1",
        )
        job2 = JobOffer(
            id="job-2",
            title="Python Dev",
            company="StartupX",
            description="Python role",
            url="http://example.com/job2",
        )

        mock_factory.scout = AsyncMock(
            return_value={
                "found_jobs": [job1, job2],
                "status": "Search complete",
            }
        )
        mock_factory.vector_manager = MagicMock()

        response = client.post(
            "/api/scout",
            json={"criteria": "Senior Python Engineer", "max_results": 10},
            headers={"Authorization": "Bearer valid_token_here"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "search_id" in data
        assert "found_jobs" in data
        assert "criteria" in data
        assert "count" in data
        assert "timestamp" in data
        assert "status" in data

        # Verify found jobs
        assert data["count"] == 2
        assert len(data["found_jobs"]) == 2
        assert data["found_jobs"][0]["title"] == "Senior Python Engineer"
        assert data["found_jobs"][0]["company"] == "TechCorp"
        assert data["criteria"] == "Senior Python Engineer"
    finally:
        # Clean up
        app.dependency_overrides.clear()


@patch("src.api.routes.search.AgentFactory")
@patch("src.api.routes.search.get_cv_context_async")
@patch("src.api.routes.search.JobRepository.create_or_update")
@patch("src.api.routes.search.SearchSessionRepository.create")
def test_scout_endpoint_missing_cv(
    mock_create_session: AsyncMock,
    mock_create_job: AsyncMock,
    mock_get_cv_context: AsyncMock,
    mock_agent_factory: MagicMock,
    client: TestClient,
) -> None:
    """Test POST /scout without CV uploaded - should warn but still search."""
    from uuid import uuid4
    from src.api.dependencies import get_current_user, get_db

    user_id = uuid4()

    # Mock authenticated user
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "test@example.com"

    def mock_get_current_user_override() -> MagicMock:
        return mock_user

    # Mock database session
    mock_session = AsyncMock()

    async def mock_get_db_override() -> AsyncMock:
        return mock_session

    # Override the dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user_override
    app.dependency_overrides[get_db] = mock_get_db_override

    try:
        # Mock CV context as empty (no CV uploaded)
        mock_get_cv_context.return_value = ""

        # Mock factory
        mock_factory = MagicMock()
        mock_agent_factory.return_value = mock_factory

        job1 = JobOffer(
            id="job-1",
            title="Python Engineer",
            company="Corp",
            description="role",
            url="http://example.com/1",
        )

        mock_factory.scout = AsyncMock(
            return_value={
                "found_jobs": [job1],
                "status": "Search complete",
            }
        )
        mock_factory.vector_manager = MagicMock()

        response = client.post(
            "/api/scout",
            json={"criteria": "Python engineer"},
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify warning in status
        assert "CV not uploaded" in data["status"]
        assert data["count"] == 1
    finally:
        # Clean up
        app.dependency_overrides.clear()


@patch("src.api.routes.search.AgentFactory")
@patch("src.api.routes.search.get_cv_context_async")
def test_scout_endpoint_scout_fails(
    mock_get_cv_context: AsyncMock,
    mock_agent_factory: MagicMock,
    client: TestClient,
) -> None:
    """Test error handling when Scout agent raises exception."""
    from uuid import uuid4
    from src.api.dependencies import get_current_user, get_db

    user_id = uuid4()

    # Mock authenticated user
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "test@example.com"

    def mock_get_current_user_override() -> MagicMock:
        return mock_user

    # Mock database session
    mock_session = AsyncMock()

    async def mock_get_db_override() -> AsyncMock:
        return mock_session

    # Override the dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user_override
    app.dependency_overrides[get_db] = mock_get_db_override

    try:
        mock_get_cv_context.return_value = "CV context"

        # Mock factory with scout that fails
        mock_factory = MagicMock()
        mock_agent_factory.return_value = mock_factory
        mock_factory.scout = AsyncMock(side_effect=Exception("OpenRouter API timeout"))
        mock_factory.vector_manager = MagicMock()

        response = client.post(
            "/api/scout",
            json={"criteria": "Python engineer"},
            headers={"Authorization": "Bearer valid_token"},
        )

        # Should return 200 with error detail (graceful degradation)
        assert response.status_code == 200
        data = response.json()

        # Verify error response format
        assert data["count"] == 0
        assert len(data["found_jobs"]) == 0
        assert "Search failed" in data["status"]
        assert data["found_jobs"] == []
    finally:
        # Clean up
        app.dependency_overrides.clear()


def test_scout_endpoint_unauthenticated(client: TestClient) -> None:
    """Test POST /scout without JWT returns 401."""
    response = client.post(
        "/api/scout",
        json={"criteria": "Python engineer"},
    )

    assert response.status_code == 401


@patch("src.api.routes.search.AgentFactory")
@patch("src.api.routes.search.get_cv_context_async")
@patch("src.api.routes.search.JobRepository.create_or_update")
@patch("src.api.routes.search.SearchSessionRepository.create")
def test_scout_endpoint_cv_context_retrieval_fails(
    mock_create_session: AsyncMock,
    mock_create_job: AsyncMock,
    mock_get_cv_context: AsyncMock,
    mock_agent_factory: MagicMock,
    client: TestClient,
) -> None:
    """Test graceful handling when CV context retrieval fails."""
    from uuid import uuid4
    from src.api.dependencies import get_current_user, get_db

    user_id = uuid4()

    # Mock authenticated user
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "test@example.com"

    def mock_get_current_user_override() -> MagicMock:
        return mock_user

    # Mock database session
    mock_session = AsyncMock()

    async def mock_get_db_override() -> AsyncMock:
        return mock_session

    # Override the dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user_override
    app.dependency_overrides[get_db] = mock_get_db_override

    try:
        # Mock CV context retrieval failure
        mock_get_cv_context.side_effect = Exception("Database connection error")

        # Mock factory
        mock_factory = MagicMock()
        mock_agent_factory.return_value = mock_factory

        job1 = JobOffer(
            id="job-1",
            title="Python Engineer",
            company="Corp",
            description="role",
            url="http://example.com/1",
        )

        mock_factory.scout = AsyncMock(
            return_value={
                "found_jobs": [job1],
                "status": "Search complete",
            }
        )
        mock_factory.vector_manager = MagicMock()

        response = client.post(
            "/api/scout",
            json={"criteria": "Python engineer"},
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.json()

        # Should warn about CV context unavailable but still return results
        assert "CV context unavailable" in data["status"]
        assert data["count"] == 1
    finally:
        # Clean up
        app.dependency_overrides.clear()


@patch("src.api.routes.search.AgentFactory")
@patch("src.api.routes.search.get_cv_context_async")
@patch("src.api.routes.search.JobRepository.create_or_update")
@patch("src.api.routes.search.SearchSessionRepository.create")
def test_scout_endpoint_response_format(
    mock_create_session: AsyncMock,
    mock_create_job: AsyncMock,
    mock_get_cv_context: AsyncMock,
    mock_agent_factory: MagicMock,
    client: TestClient,
) -> None:
    """Test that response includes all required fields in correct format."""
    from uuid import uuid4
    from src.api.dependencies import get_current_user, get_db

    user_id = uuid4()

    # Mock authenticated user
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.email = "test@example.com"

    def mock_get_current_user_override() -> MagicMock:
        return mock_user

    # Mock database session
    mock_session = AsyncMock()

    async def mock_get_db_override() -> AsyncMock:
        return mock_session

    # Override the dependencies
    app.dependency_overrides[get_current_user] = mock_get_current_user_override
    app.dependency_overrides[get_db] = mock_get_db_override

    try:
        mock_get_cv_context.return_value = "CV context"

        mock_factory = MagicMock()
        mock_agent_factory.return_value = mock_factory

        job1 = JobOffer(
            id="job-1",
            title="Python Engineer",
            company="TechCorp",
            salary_range="$100k-150k",
            description="Detailed description",
            url="http://example.com/job1",
        )

        mock_factory.scout = AsyncMock(
            return_value={
                "found_jobs": [job1],
                "status": "Search complete",
            }
        )
        mock_factory.vector_manager = MagicMock()

        response = client.post(
            "/api/scout",
            json={"criteria": "Python engineer"},
            headers={"Authorization": "Bearer valid_token"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all required fields
        required_fields = [
            "search_id",
            "found_jobs",
            "criteria",
            "count",
            "timestamp",
            "status",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

        # Verify job object fields
        job = data["found_jobs"][0]
        assert job["id"] == "job-1"
        assert job["title"] == "Python Engineer"
        assert job["company"] == "TechCorp"
        assert job["url"] == "http://example.com/job1"
        assert job["description"] == "Detailed description"
        assert job["salary_range"] == "$100k-150k"

        # Verify timestamp format (ISO 8601)
        assert "T" in data["timestamp"]
        assert "Z" in data["timestamp"] or "+" in data["timestamp"]
    finally:
        # Clean up
        app.dependency_overrides.clear()
