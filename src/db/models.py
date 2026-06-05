"""SQLAlchemy ORM models for PostgreSQL + pgvector."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import, import-untyped]
except ImportError:
    Vector = None  # type: ignore[assignment, misc]

Base = declarative_base()


class User(Base):  # type: ignore[misc, valid-type]
    """User account model for authentication and isolation."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email})>"


class CVFile(Base):  # type: ignore[misc, valid-type]
    """CV file metadata for user-uploaded resume PDFs."""

    __tablename__ = "cv_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path = Column(String(512), nullable=False)
    file_hash = Column(String(64), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=True, default=None)
    ingestion_error = Column(Text, nullable=True, default=None)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<CVFile(id={self.id}, user_id={self.user_id})>"


class CVEmbedding(Base):  # type: ignore[misc, valid-type]
    """CV text chunks and their pgvector embeddings for semantic search."""

    __tablename__ = "cv_embeddings"
    __table_args__ = (Index("ix_cv_embeddings_user_id", "user_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)  # type: ignore[arg-type, misc]
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<CVEmbedding(id={self.id}, user_id={self.user_id})>"


class Job(Base):  # type: ignore[misc, valid-type]
    """Job postings discovered by Scout agent, scoped per user."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_user_id", "user_id"),
        Index("ix_jobs_url", "url"),
    )

    id = Column(String(255), primary_key=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String(512), nullable=False)
    salary_range = Column(String(100), nullable=True)
    discovered_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, user_id={self.user_id}, title={self.title})>"


class Evaluation(Base):  # type: ignore[misc, valid-type]
    """Job match scores and evaluations from Orchestrator and Tailor agents."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_user_id", "user_id"),
        Index("ix_evaluations_job_id", "job_id"),
        UniqueConstraint("user_id", "job_id", name="uq_evaluations_user_job"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id = Column(
        String(255), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    match_score = Column(Float, nullable=False)
    orchestrator_reasoning = Column(Text, nullable=True)
    tailor_summary = Column(Text, nullable=True)
    evaluated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<Evaluation(id={self.id}, user_id={self.user_id}, job_id={self.job_id})>"
        )


class SearchSession(Base):  # type: ignore[misc, valid-type]
    """Job search sessions, one per user search request."""

    __tablename__ = "search_sessions"
    __table_args__ = (
        Index("ix_search_sessions_user_id_created_at", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criteria = Column(Text, nullable=False)
    found_count = Column(Integer, default=0)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<SearchSession(id={self.id}, user_id={self.user_id}, criteria='{self.criteria[:50]}...')>"
