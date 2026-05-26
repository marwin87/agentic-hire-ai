import asyncio
import time
import httpx
from bs4 import BeautifulSoup
from src.schema.state import JobOffer
from src.schema.validation import JobValidationResult, ValidationFailureReason
from src.config.settings import config
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any, Dict, Optional


class ExpirationCheck(BaseModel):
    is_active: bool = Field(
        description="True if the job posting is currently active and accepting applications. False if it is expired, closed, not found, or filled."
    )
    reason: str = Field(
        description="A short explanation of why the job is considered active or expired."
    )


class JobValidator:
    """
    Validates job postings to ensure they are accessible and currently active.
    Includes caching, retries, and configurable timeouts.
    """

    def __init__(self, llm: Any) -> None:
        self.checker = llm.with_structured_output(ExpirationCheck)
        self.validation_cache: Dict[str, bool] = (
            {} if config.validator_cache_enabled else {}
        )

    async def validate_job_with_reason(self, job: JobOffer) -> JobValidationResult:
        """Validate a job and return a structured result with failure reason and duration.

        Used by the API endpoint. Unlike is_job_valid(), does not catch unexpected
        exceptions — callers must handle asyncio.TimeoutError for total-job timeout.
        """
        start_ms = int(time.monotonic() * 1000)

        def elapsed_ms() -> int:
            return int(time.monotonic() * 1000) - start_ms

        if not job.url or job.url == "N/A" or not job.url.startswith("http"):
            logger.warning(f"Invalid URL format for job '{job.title}': {job.url}")
            return JobValidationResult(
                is_valid=False,
                reason_code=ValidationFailureReason.URL_INVALID,
                reason_text=f"Invalid URL: {job.url!r}",
                duration_ms=elapsed_ms(),
            )

        if config.validator_cache_enabled and job.url in self.validation_cache:
            cached = self.validation_cache[job.url]
            logger.debug(f"Cache hit for {job.url}: {cached}")
            if cached:
                return JobValidationResult(is_valid=True, duration_ms=elapsed_ms())
            return JobValidationResult(
                is_valid=False,
                reason_code=ValidationFailureReason.HTTP_ERROR,
                reason_text="Previously validated as invalid (cached)",
                duration_ms=elapsed_ms(),
            )

        try:
            logger.info(f"Validating job '{job.title}' at URL: {job.url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            async with httpx.AsyncClient(timeout=config.validator_timeout) as client:
                response = await client.get(job.url, headers=headers)

            if response.status_code >= 400:
                logger.warning(
                    f"HTTP Error {response.status_code} when accessing {job.url}"
                )
                if config.validator_cache_enabled:
                    self.validation_cache[job.url] = False
                return JobValidationResult(
                    is_valid=False,
                    reason_code=ValidationFailureReason.HTTP_ERROR,
                    reason_text=f"HTTP {response.status_code} error accessing job page",
                    duration_ms=elapsed_ms(),
                )

            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text_content = soup.get_text(separator=" ", strip=True)
            text_to_analyze = text_content[: config.validator_content_max_chars]

            result = await self._invoke_llm_with_retry(job.title, text_to_analyze)

            if not result or not result.is_active:
                reason_text = (
                    result.reason
                    if result
                    else "LLM could not determine posting status"
                )
                logger.info(
                    f"Job '{job.title}' is expired/inactive. Reason: {reason_text}"
                )
                if config.validator_cache_enabled:
                    self.validation_cache[job.url] = False
                return JobValidationResult(
                    is_valid=False,
                    reason_code=ValidationFailureReason.JOB_EXPIRED,
                    reason_text=reason_text,
                    duration_ms=elapsed_ms(),
                )

            logger.info(f"Job '{job.title}' is active.")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = True
            return JobValidationResult(is_valid=True, duration_ms=elapsed_ms())

        except httpx.TimeoutException:
            logger.error(f"Timeout ({config.validator_timeout}s) for {job.url}")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = False
            return JobValidationResult(
                is_valid=False,
                reason_code=ValidationFailureReason.VALIDATION_TIMEOUT,
                reason_text=f"HTTP request timed out after {config.validator_timeout}s",
                duration_ms=elapsed_ms(),
            )
        except httpx.HTTPError as e:
            logger.error(f"Request failed for {job.url}: {str(e)}")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = False
            return JobValidationResult(
                is_valid=False,
                reason_code=ValidationFailureReason.HTTP_ERROR,
                reason_text=f"HTTP request failed: {str(e)}",
                duration_ms=elapsed_ms(),
            )
        # Per lessons.md: unexpected exceptions (connectivity, auth, system state)
        # are not caught here — callers handle them specifically.

    async def is_job_valid(self, job: JobOffer) -> bool:
        """Backward-compatible wrapper used by the LangGraph graph node."""
        try:
            result = await self.validate_job_with_reason(job)
            return result.is_valid
        except Exception as e:
            logger.error(f"Validation error for {job.url}: {str(e)}")
            return False

    async def _invoke_llm_with_retry(
        self, job_title: str, text_to_analyze: str
    ) -> Optional[ExpirationCheck]:
        """Invoke LLM with exponential backoff retry logic."""
        prompt = f"""
            Analyze the following text extracted from a job posting webpage.
            Determine if the job posting is still active or if it has expired, closed, or the position has been filled.
            Pay attention to phrases indicating the job is no longer available in ANY language.

            Webpage Text:
            {text_to_analyze}
            """

        for attempt in range(config.validator_max_retries):
            try:
                logger.debug(
                    f"LLM expiration check for '{job_title}' (attempt {attempt + 1})"
                )
                result: ExpirationCheck = await self.checker.ainvoke(prompt)
                return result
            except Exception as e:
                if attempt < config.validator_max_retries - 1:
                    backoff = 2**attempt
                    logger.warning(f"LLM call failed, retrying in {backoff}s: {str(e)}")
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        f"LLM call failed after {config.validator_max_retries} attempts: {str(e)}"
                    )
                    return None
        return None
