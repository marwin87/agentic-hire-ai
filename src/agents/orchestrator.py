from src.schema.state import AgenticHireState, JobOffer
from src.tools.vectordb import CVVectorManager
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any
from uuid import UUID


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
            logger.info(
                f"[ORCHESTRATOR] Analyzing job match: {job.title} at {job.company}..."
            )

            # 1. RAG Step: Get specific context from CV for THIS job
            # We search for the job title and description in our vectors
            description_snippet = job.description[:200] if job.description else ""
            search_query = f"{job.title} {description_snippet}"
            # Use async method directly (pgvector queries are async-native)
            relevant_cv_parts = await self.vector_manager.get_context_async(
                search_query, 3
            )

            logger.debug(f"RAG retrieved context length: {len(relevant_cv_parts)}")

            # 2. Evaluation Step: Compare Job vs. CV Evidence
            prompt = f"""
            You are an expert Career Matchmaker. Compare the Job Description with the Candidate's Experience.

            JOB DESCRIPTION:
            {job.title} at {job.company}
            {job.description}

            CANDIDATE EVIDENCE:
            {relevant_cv_parts}

            SCORING RULES:
            - 1.0: Perfect match (all tech stack and seniority levels align).
            - 0.8: Great match (has core skills, maybe missing one secondary skill).
            - 0.6: Good match (has the foundation, can learn the rest).
            - < 0.5: Poor match.

            Consider synonyms (e.g., 'GenAI' matches 'LLM' or 'GPT').
            Don't penalize if 'Remote' isn't on the CV if the tech skills are a 100% match.
            """

            logger.debug("Requesting LLM match rating evaluation...")
            rating = await self.judge.ainvoke(prompt)

            # 3. Decision Step: Add to shortlist if it's a strong match
            if rating.score >= threshold:
                job.match_score = rating.score
                job.analysis = rating.reasoning
                shortlisted_jobs.append(job)
                logger.info(f"✅ Match accepted! Score: {rating.score}")
                logger.info(f"[ORCHESTRATOR] Reasoning: {rating.reasoning}")
            else:
                rejected_jobs.append(job)  # Add to rejected list
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
