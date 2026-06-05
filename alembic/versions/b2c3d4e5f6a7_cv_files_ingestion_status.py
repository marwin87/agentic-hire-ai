"""Add ingestion_error to cv_files and make ingested_at nullable with no default.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cv_files",
        sa.Column("ingestion_error", sa.Text(), nullable=True),
    )
    # Remove server-side default so new rows start with NULL (processing state)
    op.alter_column("cv_files", "ingested_at", server_default=None)


def downgrade() -> None:
    op.drop_column("cv_files", "ingestion_error")
    op.alter_column(
        "cv_files",
        "ingested_at",
        server_default=sa.text("now()"),
    )
