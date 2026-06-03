"""Test-support endpoints — only active when debug_mode is enabled.

Never register this router in production. The single guard is debug_mode:
if it is False the router raises 404 on every request.
"""

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.config.settings import config
from src.db import CVFile, Job, User

router = APIRouter(prefix="/api/internal", tags=["testing"])


class TestEmailRequest(BaseModel):
    email: EmailStr


def _require_debug() -> None:
    if not config.debug_mode:
        raise HTTPException(status_code=404, detail="Not found")


async def _resolve_user(email: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.delete("/test-users", status_code=204)
async def delete_test_user(
    body: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_debug),
) -> None:
    """Hard-delete a test user by email.

    Cascades to all related rows (cv_chunks, jobs, evaluations) via DB-level
    ON DELETE CASCADE. Intended for E2E test teardown only.
    """
    await db.execute(delete(User).where(User.email == body.email))
    await db.commit()


@router.post("/test-jobs", status_code=204)
async def seed_test_job(
    body: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_debug),
) -> None:
    """Insert one synthetic Job row for a test user.

    Lets E2E tests seed User A's data without running the full workflow.
    """
    user = await _resolve_user(body.email, db)
    job = Job(
        id=f"test-job-{uuid4().hex}",
        user_id=user.id,
        title="Test Job (E2E seed)",
        company="Test Corp",
        url="https://example.com/test-job",
    )
    db.add(job)
    await db.commit()


@router.post("/test-cv-file", status_code=204)
async def seed_test_cv_file(
    body: TestEmailRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_debug),
) -> None:
    """Insert one synthetic CVFile row for a test user.

    Flips has_cv to true in the CV status endpoint without a real upload.
    file_hash uses a uuid suffix to avoid unique-constraint collisions
    across parallel test runs.
    """
    user = await _resolve_user(body.email, db)
    cv_file = CVFile(
        user_id=user.id,
        file_path="test/synthetic-cv.pdf",
        file_hash=f"test-{uuid4().hex[:8]}",
    )
    db.add(cv_file)
    await db.commit()
