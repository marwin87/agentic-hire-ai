"""Database module for async SQLAlchemy with pgvector support."""

from src.db.database import init_db, close_db, get_db, get_session_factory
from src.db.models import Base, User, CVFile, CVEmbedding, Job, Evaluation, SearchSession
from src.db.repositories import (
    UserRepository,
    CVFileRepository,
    CVEmbeddingRepository,
    JobRepository,
    EvaluationRepository,
    SearchSessionRepository,
)

__all__ = [
    "init_db",
    "close_db",
    "get_db",
    "get_session_factory",
    "Base",
    "User",
    "CVFile",
    "CVEmbedding",
    "Job",
    "Evaluation",
    "SearchSession",
    "UserRepository",
    "CVFileRepository",
    "CVEmbeddingRepository",
    "JobRepository",
    "EvaluationRepository",
    "SearchSessionRepository",
]
