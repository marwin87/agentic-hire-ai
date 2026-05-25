"""Authentication endpoints for signup, login, and token refresh."""

from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_current_user
from src.api.schemas import SignupRequest, LoginRequest, RefreshRequest, TokenResponse
from src.auth import hash_password, verify_password, encode_token, decode_token, validate_password_strength
from src.config.settings import config
from src.db import User

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Sign up a new user with email and password.

    Args:
        request: SignupRequest with email, password, password_confirm
        db: Database session (injected via FastAPI dependency)

    Returns:
        TokenResponse with access_token, refresh_token, token_type, expires_in

    Raises:
        HTTPException: 400 if validation fails, 409 if email already exists
    """
    # Validate password confirmation
    if request.password != request.password_confirm:
        logger.warning("Signup attempt with mismatched passwords")
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match",
        )

    # Validate password strength
    valid, error_msg = validate_password_strength(request.password)
    if not valid:
        logger.warning(f"Signup attempt with weak password: {error_msg}")
        raise HTTPException(
            status_code=400,
            detail=error_msg,
        )

    # Check if user already exists
    try:
        result = await db.execute(select(User).where(User.email == request.email))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            logger.warning("Signup attempt with duplicate email")
            raise HTTPException(
                status_code=409,
                detail="Email already registered",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database error checking existing user: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Database error")

    # Hash password and create user
    password_hash = hash_password(request.password)
    new_user = User(email=request.email, password_hash=password_hash)

    try:
        db.add(new_user)
        await db.flush()
        await db.commit()
        logger.info(f"User registered: {new_user.id}")
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating user: {e}", exc_info=e)
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already registered")
        raise HTTPException(status_code=500, detail="Error creating user")

    # Generate tokens
    access_token = encode_token(
        {"user_id": str(new_user.id), "email": new_user.email},
        expires_in_minutes=config.jwt_access_token_expire_minutes,
        token_type="access",
    )
    refresh_token = encode_token(
        {"user_id": str(new_user.id), "email": new_user.email},
        expires_in_minutes=config.jwt_refresh_token_expire_days * 24 * 60,
        token_type="refresh",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": config.jwt_access_token_expire_minutes * 60,
    }


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Log in a user with email and password.

    Args:
        request: LoginRequest with email and password
        db: Database session (injected via FastAPI dependency)

    Returns:
        TokenResponse with access_token, refresh_token, token_type, expires_in

    Raises:
        HTTPException: 401 if email not found or password incorrect
    """
    # Query user by email
    try:
        result = await db.execute(select(User).where(User.email == request.email))
        user = result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Database error querying user: {e}", exc_info=e)
        raise HTTPException(status_code=500, detail="Database error")

    # Check if user exists and verify password (use generic message to prevent email enumeration)
    if not user or not verify_password(request.password, str(user.password_hash)):
        logger.warning("Login attempt with invalid credentials")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    logger.info(f"User logged in: {user.id}")

    # Generate tokens
    access_token = encode_token(
        {"user_id": str(user.id), "email": user.email},
        expires_in_minutes=config.jwt_access_token_expire_minutes,
        token_type="access",
    )
    refresh_token = encode_token(
        {"user_id": str(user.id), "email": user.email},
        expires_in_minutes=config.jwt_refresh_token_expire_days * 24 * 60,
        token_type="refresh",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": config.jwt_access_token_expire_minutes * 60,
    }


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Refresh an access token using a refresh token.

    Args:
        request: RefreshRequest with refresh_token
        db: Database session (injected via FastAPI dependency)

    Returns:
        TokenResponse with new access_token

    Raises:
        HTTPException: 401 if refresh token is invalid or expired
    """
    # Decode refresh token
    try:
        payload = decode_token(request.refresh_token)
    except Exception as e:
        logger.warning("Invalid refresh token attempt")
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Verify token type is refresh
    if payload.get("type") != "refresh":
        logger.warning("Refresh endpoint called with non-refresh token")
        raise HTTPException(status_code=401, detail="Token is not a refresh token")

    # Extract user_id
    user_id = payload.get("user_id")
    email = payload.get("email")

    if not user_id or not email:
        logger.warning("Refresh token missing required claims")
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    logger.info(f"Token refreshed for user: {email}")

    # Generate new access token
    access_token = encode_token(
        {"user_id": user_id, "email": email},
        expires_in_minutes=config.jwt_access_token_expire_minutes,
        token_type="access",
    )

    return {
        "access_token": access_token,
        "refresh_token": request.refresh_token,
        "token_type": "bearer",
        "expires_in": config.jwt_access_token_expire_minutes * 60,
    }


@router.post("/logout")
async def logout(user: User = Depends(get_current_user)) -> dict[str, str]:
    """Log out the current user (client-side token deletion).

    This endpoint validates the JWT token and acknowledges logout.
    In this phase, token revocation is client-side: users delete the token
    from their browser. Server-side token blacklisting is deferred to Phase 2.

    Args:
        user: Authenticated user from JWT token (validates token is valid)

    Returns:
        Success message
    """
    logger.info(f"User logged out: {user.email}")
    return {"message": "Logged out successfully"}


# Note: /dashboard is not in the /api/auth prefix, so it's registered in main.py

