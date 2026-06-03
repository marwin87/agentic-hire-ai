"""Test-support endpoints — only active when debug_mode is enabled.

Never register this router in production. The single guard is debug_mode:
if it is False the router raises 404 on every request.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.config.settings import config
from src.db import User

router = APIRouter(prefix="/api/internal", tags=["testing"])


class DeleteTestUserRequest(BaseModel):
    email: EmailStr


def _require_debug() -> None:
    if not config.debug_mode:
        raise HTTPException(status_code=404, detail="Not found")


@router.delete("/test-users", status_code=204)
async def delete_test_user(
    body: DeleteTestUserRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_require_debug),
) -> None:
    """Hard-delete a test user by email.

    Cascades to all related rows (cv_chunks, jobs, evaluations) via DB-level
    ON DELETE CASCADE. Intended for E2E test teardown only.
    """
    await db.execute(delete(User).where(User.email == body.email))
    await db.commit()
