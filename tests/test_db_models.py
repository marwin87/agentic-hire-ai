"""Tests for database models."""

import pytest
from datetime import datetime, UTC
from uuid import uuid4
from src.db.models import User, CVFile, CVEmbedding, Job, Evaluation


def test_user_model_creation() -> None:
    """Test that User model can be instantiated."""
    user = User(
        id=uuid4(),
        email="test@example.com",
        password_hash="hashed_password",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert user.email == "test@example.com"
    assert user.password_hash == "hashed_password"


def test_job_model_creation() -> None:
    """Test that Job model can be instantiated."""
    user_id = uuid4()
    job = Job(
        id="job-123",
        user_id=user_id,
        title="Python Engineer",
        company="Tech Corp",
        description="Python role",
        url="https://example.com/job",
        salary_range="$100k-$150k",
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    assert job.title == "Python Engineer"
    assert job.user_id == user_id


def test_cv_file_model_creation() -> None:
    """Test that CVFile model can be instantiated."""
    user_id = uuid4()
    cv_file = CVFile(
        id=uuid4(),
        user_id=user_id,
        file_path="/data/cv/user-123.pdf",
        file_hash="abc123def456",
        ingested_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert cv_file.file_path == "/data/cv/user-123.pdf"
    assert cv_file.user_id == user_id


def test_evaluation_model_creation() -> None:
    """Test that Evaluation model can be instantiated."""
    user_id = uuid4()
    evaluation = Evaluation(
        id=uuid4(),
        user_id=user_id,
        job_id="job-123",
        match_score=0.85,
        orchestrator_reasoning="Good match",
        tailor_summary="Worth applying",
        evaluated_at=datetime.now(UTC),
    )
    assert evaluation.match_score == 0.85
    assert evaluation.user_id == user_id
