from src.schema.state import AgenticHireState, JobOffer
from src.tools.vectordb import CVVectorManager
from src.utils.progress import emit
from src.config.settings import config
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any
from uuid import UUID

_MATCH_PROMPT_TEMPLATE = """\
You are an expert Career Matchmaker. Compare the Job Description with the Candidate's Experience.

JOB DESCRIPTION:
{title} at {company}
{description}

CANDIDATE EVIDENCE:
{cv_context}

SCORING RULES:
- 1.0: Perfect match (all tech stack and seniority levels align).
- 0.8: Great match (has core skills, maybe missing one secondary skill).
- 0.6: Good match (has the foundation, can learn the rest).
- < 0.5: Poor match.

Consider synonyms (e.g., 'GenAI' matches 'LLM' or 'GPT').
Don't penalize if 'Remote' isn't on the CV if the tech skills are a 100% match.

FEW-SHOT EXAMPLES:
• Score 1.0 — Job: "Senior Python Engineer, Django + PostgreSQL, 5+ yrs". CV: "6 yrs Django, PostgreSQL admin, DRF". All required tech and seniority align exactly.
• Score 0.8 — Job: "ML Engineer, PyTorch, MLflow, AWS". CV: "Python ML, TensorFlow, DVC, GCP". Core ML skills match; different framework/cloud, both easily transferable.
• Score 0.6 — Job: "Backend Developer, Go + gRPC, 3+ yrs". CV: "Python backend, REST APIs, 2 yrs". Foundation present; Go would need ramping, seniority close enough.
• Score 0.3 — Job: "iOS Developer, Swift + SwiftUI, 4+ yrs". CV: "Python web developer, Django, React". No mobile, no Swift — fundamentally different stack.\
"""


class MatchRating(BaseModel):
    """Structured output for the matching logic."""

    score: float = Field(description="Match score between 0.0 and 1.0")
    reasoning: str = Field(description="Brief explanation of why this score was given")


class OrchestratorAgent:
    """
    The Matchmaker. It compares found jobs against the candidate's actual
    experience stored in pgvector and filters for the best fits.
    Uses user-filtered RAG to retrieve only the relevant candidate's CV chunks.
    """

    def __init__(
        self, llm: Any, vector_manager: CVVectorManager, user_id: UUID
    ) -> None:
        self.llm = llm
        # Initialize the Vector DB manager to fetch CV context (pgvector backend)
        self.vector_manager = vector_manager
        self.user_id = user_id
        # Create a structured judge
        self.judge = self.llm.with_structured_output(MatchRating)

    async def __call__(self, state: AgenticHireState) -> dict[str, Any]:
        logger.info("--- [NODE] EXECUTING ORCHESTRATOR (MATCHMAKER) ---")

        valid_jobs = state.get("valid_jobs", [])
        threshold: float = state.get("score_threshold", 0.6)
        shortlisted_jobs = []
        rejected_jobs = []  # New list to track rejections

        if not valid_jobs:
            logger.warning("[ORCHESTRATOR] No valid jobs found to analyze.")
            return {"status": "Orchestrator skipped: No valid jobs found."}

        logger.debug(f"Orchestrator evaluating {len(valid_jobs)} valid jobs.")

        for job in valid_jobs:
            await emit("orchestrator", f"Scoring: {job.title} @ {job.company}")
            logger.info(
                f"[ORCHESTRATOR] Analyzing job match: {job.title} at {job.company}..."
            )

            # 1. RAG Step: Get specific context from CV for THIS job
            # We search for the job title and description in our vectors
            description_snippet = (
                job.description[: config.orchestrator_description_snippet_chars]
                if job.description
                else ""
            )
            search_query = f"{job.title} {description_snippet}"
            # Use async method directly (pgvector queries are async-native)
            relevant_cv_parts = await self.vector_manager.get_context_async(
                search_query, config.orchestrator_rag_context_chunks
            )

            logger.debug(f"RAG retrieved context length: {len(relevant_cv_parts)}")

            # 2. Evaluation Step: Compare Job vs. CV Evidence
            prompt = _MATCH_PROMPT_TEMPLATE.format(
                title=job.title,
                company=job.company,
                description=job.description or "",
                cv_context=relevant_cv_parts,
            )

            logger.debug("Requesting LLM match rating evaluation...")
            rating = await self.judge.ainvoke(prompt)

            # 3. Decision Step: Add to shortlist if it's a strong match
            if rating.score >= threshold:
                scored_job = job.model_copy(
                    update={"match_score": rating.score, "analysis": rating.reasoning}
                )
                shortlisted_jobs.append(scored_job)
                await emit("orchestrator", f"  → {int(rating.score * 100)}% match ✅")
                logger.info(f"✅ Match accepted! Score: {rating.score}")
                logger.info(f"[ORCHESTRATOR] Reasoning: {rating.reasoning}")
            else:
                rejected_jobs.append(job)
                await emit(
                    "orchestrator",
                    f"  → {int(rating.score * 100)}% match ❌ (below threshold)",
                )
                logger.info(
                    f"❌ Match rejected. Score ({rating.score}) below threshold ({threshold})."
                )
                logger.debug(f"[ORCHESTRATOR] Reasoning: {rating.reasoning}")

        # Sorting shortlisted jobs by score (descending)
        shortlisted_jobs.sort(key=lambda x: x.match_score, reverse=True)

        logger.info(f"[ORCHESTRATOR] Shortlisted {len(shortlisted_jobs)} jobs.")

        return {
            "shortlisted_jobs": shortlisted_jobs,
            "rejected_jobs": rejected_jobs,
            "status": f"Orchestrator shortlisted {len(shortlisted_jobs)} jobs.",
        }
