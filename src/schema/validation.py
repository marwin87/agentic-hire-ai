"""Validation-related schemas for the job validation endpoint."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.schema.state import JobOffer


class ValidationFailureReason(str, Enum):
    """Machine-readable reason codes for job validation failure."""

    URL_INVALID = "URL_INVALID"
    HTTP_ERROR = "HTTP_ERROR"
    JOB_EXPIRED = "JOB_EXPIRED"
    VALIDATION_TIMEOUT = "VALIDATION_TIMEOUT"


class JobValidationResult(BaseModel):
    """Internal result returned by JobValidator.validate_job_with_reason()."""

    is_valid: bool
    reason_code: Optional[ValidationFailureReason] = None
    reason_text: str = ""
    duration_ms: int = 0


class RejectedJob(BaseModel):
    """A job that failed validation, including the structured rejection reason."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "job-42",
                "title": "Senior Python Engineer",
                "company": "Acme Corp",
                "url": "https://example.com/jobs/42",
                "description": "Build scalable Python services.",
                "salary_range": "$120k-$160k",
                "reason_code": "JOB_EXPIRED",
                "reason_text": "Position has been filled",
                "validation_duration_ms": 340,
            }
        }
    )

    id: str = Field(..., description="Job ID")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    url: str = Field(..., description="Job URL")
    description: Optional[str] = Field(None, description="Job description")
    salary_range: Optional[str] = Field(None, description="Salary range")
    reason_code: ValidationFailureReason = Field(
        ...,
        description=(
            "Machine-readable failure reason. "
            "URL_INVALID — malformed or placeholder URL. "
            "HTTP_ERROR — job page returned 4xx/5xx. "
            "JOB_EXPIRED — LLM detected posting is closed/filled. "
            "VALIDATION_TIMEOUT — validation exceeded per-job time limit."
        ),
    )
    reason_text: str = Field(..., description="Human-readable failure explanation")
    validation_duration_ms: int = Field(
        0, description="Time taken to validate in milliseconds"
    )


class ValidateJobsResponse(BaseModel):
    """Response body for POST /api/validate_jobs. Always HTTP 200."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "valid_jobs": [
                    {
                        "id": "job-1",
                        "title": "Python Developer",
                        "company": "Tech Corp",
                        "url": "https://example.com/jobs/1",
                        "description": "Build Python services.",
                        "salary_range": "$100k",
                        "match_score": 0.0,
                        "analysis": None,
                    }
                ],
                "rejected_jobs": [
                    {
                        "id": "job-2",
                        "title": "Go Engineer",
                        "company": "Old Corp",
                        "url": "https://example.com/jobs/2",
                        "description": None,
                        "salary_range": None,
                        "reason_code": "JOB_EXPIRED",
                        "reason_text": "Position has been filled",
                        "validation_duration_ms": 280,
                    }
                ],
            }
        }
    )

    valid_jobs: list[JobOffer] = Field(
        default_factory=list,
        description="Jobs that passed all validation checks",
    )
    rejected_jobs: list[RejectedJob] = Field(
        default_factory=list,
        description="Jobs that failed validation with structured rejection reasons",
    )
