"""Convert all TIMESTAMP WITHOUT TIME ZONE columns to TIMESTAMP WITH TIME ZONE.

Rationale: asyncpg 0.31.0 rejects timezone-aware datetime objects when inserting
into TIMESTAMP WITHOUT TIME ZONE columns.  All application code (including
EvaluationRepository.upsert) uses datetime.now(timezone.utc) (timezone-aware),
so the column type must match.  Existing UTC-stored values are re-interpreted
as UTC via the USING clause — no data is lost.

Revision ID: a1b2c3d4e5f6
Revises: 6cfe28947e05
Create Date: 2026-06-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "6cfe28947e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "users",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_files",
        "ingested_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="ingested_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_files",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_embeddings",
        "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "jobs",
        "discovered_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="discovered_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "jobs",
        "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "evaluations",
        "evaluated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="evaluated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "search_sessions",
        "created_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "created_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "users",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_files",
        "ingested_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="ingested_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_files",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "cv_embeddings",
        "created_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "jobs",
        "discovered_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="discovered_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "jobs",
        "created_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "evaluations",
        "evaluated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="evaluated_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "search_sessions",
        "created_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
