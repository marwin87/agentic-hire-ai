"""Initial schema with pgvector extension.

Revision ID: 001
Revises:
Create Date: 2026-05-25 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial schema with users, jobs, cv_embeddings, evaluations, cv_files tables."""
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Create cv_files table
    op.create_table(
        "cv_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cv_files_user_id", "cv_files", ["user_id"])

    # Create cv_embeddings table
    op.create_table(
        "cv_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.UUID(as_uuid=True), nullable=False),  # Will be vector(1536) after migration
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cv_embeddings_user_id", "cv_embeddings", ["user_id"])

    # Create jobs table
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("salary_range", sa.String(100), nullable=True),
        sa.Column("discovered_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])
    op.create_index("ix_jobs_url", "jobs", ["url"])

    # Create evaluations table
    op.create_table(
        "evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(255), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("orchestrator_reasoning", sa.Text(), nullable=True),
        sa.Column("tailor_summary", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluations_user_id", "evaluations", ["user_id"])
    op.create_index("ix_evaluations_job_id", "evaluations", ["job_id"])

    # Add pgvector column after table creation
    op.execute(
        """
        ALTER TABLE cv_embeddings
        DROP COLUMN embedding,
        ADD COLUMN embedding vector(1536) NOT NULL
        """
    )


def downgrade() -> None:
    """Drop all schema objects and pgvector extension."""
    # Drop tables in reverse order
    op.drop_index("ix_evaluations_job_id", "evaluations")
    op.drop_index("ix_evaluations_user_id", "evaluations")
    op.drop_table("evaluations")

    op.drop_index("ix_jobs_url", "jobs")
    op.drop_index("ix_jobs_user_id", "jobs")
    op.drop_table("jobs")

    op.drop_index("ix_cv_embeddings_user_id", "cv_embeddings")
    op.drop_table("cv_embeddings")

    op.drop_index("ix_cv_files_user_id", "cv_files")
    op.drop_table("cv_files")

    op.drop_index("ix_users_email", "users")
    op.drop_table("users")

    # Drop pgvector extension
    op.execute("DROP EXTENSION IF EXISTS vector")
