from typing import Annotated, List, TypedDict, Optional
import operator
from uuid import UUID
from pydantic import BaseModel, Field


class JobOffer(BaseModel):
    """
    Structured model for a single job posting.
    Using Pydantic allows for easy validation and LLM structured output.
    """

    id: str = Field(..., description="Unique identifier for the job post")
    title: str = Field(description="Job title")
    company: str = Field(description="Company name")
    description: Optional[str] = Field(
        default=None, description="Full text of the job description"
    )
    url: str = Field(description="Direct link to the posting")
    salary_range: Optional[str] = Field(
        default=None, description="Salary info if available"
    )
    match_score: float = Field(
        default=0.0, description="Semantic match score from 0 to 1"
    )
    analysis: Optional[str] = Field(
        default=None, description="Orchestrator's reasoning for this match"
    )


def deduplicate_seen_jobs(existing: List[str], new: List[str]) -> List[str]:
    """Reducer function to maintain a unique list of seen job URLs in the state."""
    return list(set((existing or []) + (new or [])))


class _AgenticHireStateRequired(TypedDict):
    """Fields that must be present when creating initial workflow state."""

    target_criteria: str
    resume_context: str
    found_jobs: Annotated[List[JobOffer], operator.add]
    valid_jobs: List[JobOffer]
    shortlisted_jobs: List[JobOffer]
    applications: dict[str, dict[str, str]]
    status: str
    max_offers: int
    scout_runs: int
    rejected_jobs: Annotated[List[JobOffer], operator.add]
    seen_jobs: Annotated[List[str], deduplicate_seen_jobs]


class AgenticHireState(_AgenticHireStateRequired, total=False):
    """
    The shared state of the LangGraph workflow.

    Required fields are defined in _AgenticHireStateRequired (total=True).
    Optional fields below are absent from single-user/simple invocations.
    """

    # Multi-user isolation — absent in single-user (CLI) mode
    user_id: UUID

    # Minimum match score to shortlist a job (defaults to 0.6 inside orchestrator)
    score_threshold: float
