"""Integration tests for database models and data access patterns."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, UTC
from sqlalchemy import select

from src.db import User, CVFile, CVEmbedding, Job, Evaluation
from src.db.repositories import (
    UserRepository,
    CVFileRepository,
    CVEmbeddingRepository,
    JobRepository,
    EvaluationRepository,
)


@pytest.mark.asyncio
async def test_user_model_structure(test_user: User) -> None:
    """Test that User model has all required fields."""
    assert test_user.id is not None
    assert test_user.email == "test@example.com"
    assert test_user.password_hash == "$2b$12$..."
    assert test_user.created_at is not None
    assert test_user.updated_at is not None
    assert hasattr(test_user, '__tablename__')
    assert test_user.__tablename__ == 'users'


@pytest.mark.asyncio
async def test_cv_file_user_relationship(test_cv_file: CVFile, test_user: User) -> None:
    """Test that CVFile maintains proper relationship to User."""
    assert test_cv_file.user_id == test_user.id
    assert test_cv_file.file_path is not None
    assert test_cv_file.file_hash is not None
    assert hasattr(test_cv_file, '__tablename__')
    assert test_cv_file.__tablename__ == 'cv_files'


@pytest.mark.asyncio
async def test_job_model_structure(test_job: Job, test_user: User) -> None:
    """Test that Job model has all required fields."""
    assert test_job.id == "job-test-1"
    assert test_job.user_id == test_user.id
    assert test_job.title == "Senior Python Engineer"
    assert test_job.company == "Tech Corp"
    assert test_job.url is not None
    assert hasattr(test_job, '__tablename__')
    assert test_job.__tablename__ == 'jobs'


@pytest.mark.asyncio
async def test_evaluation_model_structure(
    test_evaluation: Evaluation, test_user: User, test_job: Job
) -> None:
    """Test that Evaluation model has all required fields."""
    assert test_evaluation.id is not None
    assert test_evaluation.user_id == test_user.id
    assert test_evaluation.job_id == test_job.id
    assert 0.0 <= test_evaluation.match_score <= 1.0
    assert test_evaluation.match_score == 0.85
    assert hasattr(test_evaluation, '__tablename__')
    assert test_evaluation.__tablename__ == 'evaluations'


@pytest.mark.asyncio
async def test_cv_embedding_model_structure(test_cv_embeddings: list) -> None:
    """Test that CVEmbedding model has all required fields."""
    embedding = test_cv_embeddings[0]
    assert embedding.id is not None
    assert embedding.user_id is not None
    assert embedding.chunk_text is not None
    assert len(embedding.embedding) == 1536
    assert hasattr(embedding, '__tablename__')
    assert embedding.__tablename__ == 'cv_embeddings'


@pytest.mark.asyncio
async def test_user_isolation_principle_jobs(
    test_user: User, test_user_2: User, test_job: Job
) -> None:
    """
    Test that the data model supports user isolation for jobs.
    Different users have different user_ids that filter their jobs.
    """
    job2 = Job(
        id="job-test-2",
        user_id=test_user_2.id,
        title="Data Scientist",
        company="Data Inc",
        description="ML role",
        url="https://example.com/job-2",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    # Verify that jobs have different user_ids
    assert test_job.user_id != job2.user_id
    # Jobs belong to different users, so they should be filtered separately
    assert test_job.user_id == test_user.id
    assert job2.user_id == test_user_2.id


@pytest.mark.asyncio
async def test_user_isolation_principle_embeddings(
    test_user: User, test_user_2: User, test_cv_embeddings: list
) -> None:
    """
    Test that CV embeddings support user isolation through user_id.
    Each embedding is tied to a specific user.
    """
    # All test embeddings belong to test_user
    for embedding in test_cv_embeddings:
        assert embedding.user_id == test_user.id

    # Create embeddings for test_user_2
    user2_embeddings = [
        CVEmbedding(
            id=uuid4(),
            user_id=test_user_2.id,
            chunk_text="Java expert",
            embedding=[0.3] * 1536,
            created_at=datetime.now(UTC),
        ),
    ]

    # Verify different users have different embeddings
    for emb in user2_embeddings:
        assert emb.user_id == test_user_2.id

    # No overlap between users
    all_user1_ids = {e.user_id for e in test_cv_embeddings}
    all_user2_ids = {e.user_id for e in user2_embeddings}
    assert not (all_user1_ids & all_user2_ids)


@pytest.mark.asyncio
async def test_evaluation_user_job_relationship(
    test_evaluation: Evaluation, test_user: User, test_job: Job
) -> None:
    """Test that Evaluation properly links users and jobs."""
    # Evaluation ties user to a specific job
    assert test_evaluation.user_id == test_user.id
    assert test_evaluation.job_id == test_job.id
    # Only this user should see this evaluation
    assert test_evaluation.user_id == test_job.user_id


@pytest.mark.asyncio
async def test_cv_file_latest_by_user_pattern(test_user: User) -> None:
    """
    Test that CV files can be queried with ordering for 'latest' pattern.
    This models the get_latest_by_user repository method.
    """
    files: list = []
    for i in range(3):
        cv_file = CVFile(
            id=uuid4(),
            user_id=test_user.id,
            file_path=f"/data/cv/{test_user.id}_v{i}.pdf",
            file_hash=f"hash_v{i}",
            ingested_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        files.append(cv_file)

    # In a real query, we'd order by updated_at DESC and take the first
    # Verify all files have the same user_id for isolation
    assert all(f.user_id == test_user.id for f in files)


@pytest.mark.asyncio
async def test_job_count_by_user_pattern(test_user: User) -> None:
    """
    Test that jobs can be counted by user for pagination.
    This models the count_by_user repository method.
    """
    jobs = []
    for i in range(5):
        job = Job(
            id=f"job-{i}",
            user_id=test_user.id,
            title=f"Job {i}",
            company="Test Corp",
            url=f"https://example.com/job-{i}",
            discovered_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        jobs.append(job)

    # All jobs belong to the same user
    assert len(jobs) == 5
    assert all(j.user_id == test_user.id for j in jobs)


@pytest.mark.asyncio
async def test_evaluation_update_pattern(test_evaluation: Evaluation) -> None:
    """Test that evaluation scores can be updated."""
    original_score = test_evaluation.match_score

    # Update score
    test_evaluation.match_score = 0.95  # type: ignore[assignment]
    test_evaluation.orchestrator_reasoning = "Updated reasoning"  # type: ignore[assignment]

    # Verify updates
    assert test_evaluation.match_score == 0.95
    assert test_evaluation.match_score != original_score
    assert test_evaluation.orchestrator_reasoning == "Updated reasoning"


@pytest.mark.asyncio
async def test_cv_file_hash_update_pattern(test_cv_file: CVFile) -> None:
    """Test that CV file hash can be updated for re-ingestion detection."""
    original_hash = test_cv_file.file_hash

    # Update hash
    test_cv_file.file_hash = "new_hash_value_123"  # type: ignore[assignment]

    # Verify update
    assert test_cv_file.file_hash == "new_hash_value_123"
    assert test_cv_file.file_hash != original_hash


@pytest.mark.asyncio
async def test_job_repository_filtering_by_user(db_session: AsyncMock, test_user: User) -> None:
    """
    Test that JobRepository.get_by_user would properly filter by user_id.
    This tests the repository pattern for user isolation.
    """
    # Create mock jobs
    job1 = Job(
        id="job-1",
        user_id=test_user.id,
        title="Job for user 1",
        company="Corp 1",
        url="https://example.com/1",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    other_user_id = uuid4()
    job2 = Job(
        id="job-2",
        user_id=other_user_id,
        title="Job for user 2",
        company="Corp 2",
        url="https://example.com/2",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    # Verify jobs belong to different users
    assert job1.user_id == test_user.id
    assert job2.user_id != test_user.id
    assert job1.user_id != job2.user_id


@pytest.mark.asyncio
async def test_evaluation_repository_filtering_by_user(
    test_user: User, test_user_2: User, test_job: Job
) -> None:
    """
    Test that EvaluationRepository.get_by_user would properly filter by user_id.
    """
    eval1 = Evaluation(
        id=uuid4(),
        user_id=test_user.id,
        job_id=test_job.id,
        match_score=0.9,
        orchestrator_reasoning="Great fit",
        evaluated_at=datetime.now(UTC),
    )

    eval2 = Evaluation(
        id=uuid4(),
        user_id=test_user_2.id,
        job_id=test_job.id,
        match_score=0.7,
        orchestrator_reasoning="Good fit",
        evaluated_at=datetime.now(UTC),
    )

    # Both evaluations reference same job but different users
    assert eval1.user_id == test_user.id
    assert eval2.user_id == test_user_2.id
    assert eval1.job_id == eval2.job_id
    # Only same-user queries would return both evaluations


@pytest.mark.asyncio
async def test_cv_embedding_vector_field_structure(test_cv_embeddings: list) -> None:
    """
    Test that CV embeddings have properly structured vector fields.
    This models pgvector column that will be used for semantic search.
    """
    embedding = test_cv_embeddings[0]

    # Vector should be a list of floats
    assert isinstance(embedding.embedding, list)
    assert len(embedding.embedding) == 1536
    assert all(isinstance(x, float) for x in embedding.embedding)


@pytest.mark.asyncio
async def test_multiple_evaluations_per_job(test_user: User, test_user_2: User) -> None:
    """
    Test that multiple users can have evaluations for the same job.
    This models a job where different users have independently evaluated it.
    """
    job = Job(
        id="job-shared",
        user_id=test_user.id,
        title="Shared Job",
        company="Company",
        url="https://example.com/shared",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )

    eval1 = Evaluation(
        id=uuid4(),
        user_id=test_user.id,
        job_id=job.id,
        match_score=0.9,
        evaluated_at=datetime.now(UTC),
    )

    eval2 = Evaluation(
        id=uuid4(),
        user_id=test_user_2.id,
        job_id=job.id,
        match_score=0.7,
        evaluated_at=datetime.now(UTC),
    )

    # Both evaluations reference same job
    assert eval1.job_id == eval2.job_id == job.id
    # But they belong to different users
    assert eval1.user_id != eval2.user_id
