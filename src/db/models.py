"""SQLAlchemy ORM models for PostgreSQL + pgvector."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Text,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base

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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    ingested_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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
        index=True,
    )
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=False)  # type: ignore[arg-type, misc]
    created_at = Column(DateTime, default=datetime.utcnow)

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
        index=True,
    )
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String(512), nullable=False)
    salary_range = Column(String(100), nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, user_id={self.user_id}, title={self.title})>"


class Evaluation(Base):  # type: ignore[misc, valid-type]
    """Job match scores and evaluations from Orchestrator and Tailor agents."""

    __tablename__ = "evaluations"
    __table_args__ = (
        Index("ix_evaluations_user_id", "user_id"),
        Index("ix_evaluations_job_id", "job_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id = Column(String(255), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    match_score = Column(Float, nullable=False)
    orchestrator_reasoning = Column(Text, nullable=True)
    tailor_summary = Column(Text, nullable=True)
    evaluated_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Evaluation(id={self.id}, user_id={self.user_id}, job_id={self.job_id})>"
