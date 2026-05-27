"""Pydantic models for FastAPI request/response validation."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, EmailStr

from src.schema.state import JobOffer


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
        default=10, description="Maximum number of results to return", ge=1, le=100
    )


class ValidateJobsRequest(BaseModel):
    """Request body for POST /validate_jobs endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "jobs": [
                    {
                        "id": "job-1",
                        "title": "Python Developer",
                        "company": "Tech Corp",
                        "url": "https://example.com/jobs/1",
                        "description": "Build scalable Python services.",
                        "salary_range": "$100k",
                    },
                    {
                        "id": "job-2",
                        "title": "Go Engineer",
                        "company": "Old Corp",
                        "url": "https://expired-company.com/jobs/2",
                    },
                ]
            }
        }
    )

    jobs: list[JobOffer] = Field(
        ..., description="List of jobs to validate (from Scout agent)"
    )


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


# CV upload endpoints schemas


class UploadCVResponse(BaseModel):
    """Response model for CV upload endpoint."""

    file_id: str = Field(..., description="CVFile.id UUID")
    file_path: str = Field(..., description="Relative path where file is stored")
    file_hash: str = Field(..., description="SHA256 hash of the uploaded file")
    chunks_stored: int = Field(..., description="Number of embedding chunks created")
    status: str = Field(..., description="Upload status ('success' or error code)")


# Orchestrate endpoint schemas


class OrchestrateRequest(BaseModel):
    """Request body for POST /orchestrate endpoint."""

    criteria: Optional[str] = Field(
        None,
        description="Job search criteria for Scout agent (if omitted, use provided jobs)",
    )
    jobs: Optional[list[JobOffer]] = Field(
        None,
        description="Pre-found jobs to score directly (if omitted, run scout with criteria)",
    )
    score_threshold: float = Field(
        default=0.6,
        description="Minimum match score to include in response (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "description": "Search-based orchestration",
                    "value": {
                        "criteria": "Python developer roles in AI/ML startups",
                        "score_threshold": 0.6,
                    },
                },
                {
                    "description": "Pre-found jobs orchestration",
                    "value": {
                        "jobs": [
                            {
                                "id": "job-1",
                                "title": "Senior Python Engineer",
                                "company": "TechCorp",
                                "url": "https://techcorp.com/jobs/1",
                                "description": "Build scalable backend services",
                                "salary_range": "$150k-$200k",
                            }
                        ],
                        "score_threshold": 0.5,
                    },
                },
            ]
        }


class OrchestrateJobResult(BaseModel):
    """Individual job result in orchestrate response."""

    id: str = Field(..., description="Job ID")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    url: str = Field(..., description="Job URL")
    match_score: float = Field(
        ..., description="Match score from 0.0 to 1.0 (0 if not scored)"
    )
    analysis: Optional[str] = Field(None, description="Orchestrator reasoning")
    evaluation: Optional[str] = Field(
        None, description="Tailor-generated evaluation (if shortlisted)"
    )
    error: Optional[str] = Field(
        None, description="Error message if job failed to process"
    )


class OrchestrateResponse(BaseModel):
    """Response model for POST /orchestrate endpoint."""

    all_jobs: list[OrchestrateJobResult] = Field(
        ..., description="All processed jobs with match scores and evaluations"
    )
    shortlisted_jobs: list[OrchestrateJobResult] = Field(
        ..., description="Jobs above score threshold with evaluations"
    )
    rejected_jobs: list[OrchestrateJobResult] = Field(
        ..., description="Jobs below score threshold"
    )
    status: str = Field(..., description="Overall operation status message")
    error_count: int = Field(
        ..., description="Number of jobs that failed orchestration/tailor"
    )


# Job list endpoint schemas


class JobListItemResponse(BaseModel):
    """Individual job item in job list response."""

    id: str = Field(..., description="Job ID from Scout agent")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    url: str = Field(..., description="Job posting URL")
    match_score: Optional[float] = Field(
        None,
        description="Match score from 0.0 to 1.0, null if job not yet evaluated",
        ge=0.0,
        le=1.0,
    )


class GetJobsResponse(BaseModel):
    """Response model for GET /jobs endpoint."""

    page: int = Field(..., description="Current page number (1-indexed)", ge=1)
    total_count: int = Field(
        ..., description="Total number of jobs for this user", ge=0
    )
    page_size: int = Field(..., description="Number of items per page", ge=1, le=50)
    jobs: list[JobListItemResponse] = Field(
        ..., description="Job items for current page"
    )
