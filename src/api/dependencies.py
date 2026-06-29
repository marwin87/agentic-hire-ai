"""FastAPI dependency injection utilities."""

from typing import Any

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import jwt as pyjwt

from src.agents.agents import get_agent_factory
from src.config.settings import config
from src.db import get_session_factory, get_db, User
from src.auth import decode_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """Extract and validate JWT token, return authenticated user.

    This dependency enforces JWT authentication on protected endpoints.
    Validates token signature, expiration, and user existence.

    Args:
        credentials: HTTP Bearer token from Authorization header (via HTTPBearer)

    Returns:
        User object from database

    Raises:
        HTTPException: 401 if token invalid/expired, 403 if missing credentials
    """
    token = credentials.credentials

    # Decode and validate token
    try:
        payload = decode_token(token)
    except (pyjwt.ExpiredSignatureError, pyjwt.DecodeError, pyjwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Extract user_id from token
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    # Query user from database
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user  # type: ignore[no-any-return]
