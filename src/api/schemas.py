"""Pydantic models for FastAPI request/response validation."""

from typing import Any, Optional

from pydantic import BaseModel, Field, EmailStr


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str = Field(..., description="Error type (e.g., 'validation_error')")
    detail: str = Field(..., description="Human-readable error message")
    code: str = Field(..., description="Machine-readable error code")


class HealthCheckResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="Health status: 'ok' or 'degraded'")


# Placeholder schemas for future phases
# These will be expanded with actual request/response bodies in phases 2-4


class SearchJobsRequest(BaseModel):
    """Request body for POST /search_jobs endpoint."""

    criteria: str = Field(..., description="Job search criteria")
    max_results: Optional[int] = Field(
        default=10, description="Maximum number of results to return"
    )


class ValidateJobsRequest(BaseModel):
    """Request body for POST /validate_jobs endpoint."""

    jobs: list[dict[str, Any]] = Field(..., description="List of jobs to validate")


class ScoreJobsRequest(BaseModel):
    """Request body for POST /score_jobs endpoint."""

    jobs: list[dict[str, Any]] = Field(..., description="List of jobs to score")


class EvaluateJobRequest(BaseModel):
    """Request body for POST /evaluate_job/{job_id} endpoint."""

    job_id: str = Field(..., description="Job ID")
    job: dict[str, Any] = Field(..., description="Job object to evaluate")


# Auth endpoints schemas


class SignupRequest(BaseModel):
    """Request body for POST /auth/signup endpoint."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")
    password_confirm: str = Field(
        ..., description="Password confirmation (must match password)"
    )


class LoginRequest(BaseModel):
    """Request body for POST /auth/login endpoint."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class RefreshRequest(BaseModel):
    """Request body for POST /auth/refresh endpoint."""

    refresh_token: str = Field(..., description="Refresh token from login/signup")


class TokenResponse(BaseModel):
    """Response model for auth endpoints returning JWT tokens."""

    access_token: str = Field(..., description="JWT access token")
    refresh_token: Optional[str] = Field(
        None, description="JWT refresh token (not included on refresh endpoint)"
    )
    token_type: str = Field(..., description="Token type (always 'bearer')")
    expires_in: int = Field(..., description="Access token expiration time in seconds")
