from langchain_core.messages import SystemMessage, HumanMessage
from src.schema.state import AgenticHireState
from src.utils.progress import emit
from urllib.parse import urlparse
from loguru import logger
from typing import Any


class TailorAgent:
    """
    The Tailor takes the shortlisted jobs and the candidate's CV context
    to generate highly personalized application materials.
    """

    def __init__(self, llm: Any) -> None:
        self.llm = llm

    async def __call__(self, state: AgenticHireState) -> dict[str, Any]:
        logger.info("--- [NODE] EXECUTING TAILOR (CONTENT GENERATION) ---")

        shortlisted_jobs = state.get("shortlisted_jobs", [])
        resume_context = state.get("resume_context", "")

        if not shortlisted_jobs:
            logger.warning(
                "[TAILOR] No shortlisted jobs found. Tailor has nothing to do."
            )
            return {"status": "Tailor skipped: No jobs to process."}

        applications = {}

        logger.debug(
            f"Tailoring applications for {len(shortlisted_jobs)} shortlisted jobs."
        )

        for job in shortlisted_jobs:
            await emit("tailor", f"Writing insight for: {job.title} @ {job.company}")
            logger.info(
                f"[TAILOR] Generating application materials for: {job.title} at {job.company}..."
            )

            prompt = f"""
            You are a highly critical and skeptical Career Advisor. 
            Your goal is to evaluate if it's genuinely worth applying for this job, returning ONLY a single sentence.

            CANDIDATE CV CONTEXT:
            {resume_context}

            TARGET JOB:
            Title: {job.title}
            Company: {job.company}
            Description: {job.description}

            MATCH REASONING (from Orchestrator):
            {job.analysis}

            INSTRUCTIONS:
            1. Analyze the match between the CV and the job description.
            2. Be skeptical. Look for reasons why it might NOT be a great fit (e.g., missing skills, seniority mismatch).
            3. Write EXACTLY ONE concise sentence stating whether it's worth applying or not, and briefly why.
            """

            # Generate the content
            logger.debug("Requesting LLM to generate tailor analysis...")
            response = await self.llm.ainvoke(
                [
                    SystemMessage(
                        content="You are a highly critical and skeptical Career Advisor."
                    ),
                    HumanMessage(content=prompt),
                ]
            )

            # Extract portal from URL
            portal = "Unknown Portal"
            if job.url:
                try:
                    portal = urlparse(job.url).netloc.replace("www.", "")
                except Exception as e:
                    logger.debug(f"Failed to parse URL {job.url}: {e}")
                    pass

            founded_job_offer = f"{portal} -> {job.url}\n\n{response.content}"

            applications[job.id] = {
                "founded_job_offer": founded_job_offer,
                "job_title": job.title,
                "company": job.company,
            }
            logger.info(f"[TAILOR] {founded_job_offer}")
            logger.debug(f"Tailored application generated for {job.id}")

        logger.info(
            f"[TAILOR] Generated {len(applications)} personalized applications."
        )
        return {
            "applications": applications,
            "status": f"Tailor generated {len(applications)} personalized applications.",
        }
