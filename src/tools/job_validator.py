import asyncio
import httpx
from bs4 import BeautifulSoup
from src.schema.state import JobOffer
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
        """
        Initialize the JobValidator with an LLM instance.
        """
        self.checker = llm.with_structured_output(ExpirationCheck)
        self.validation_cache: Dict[str, bool] = (
            {} if config.validator_cache_enabled else {}
        )

    async def is_job_valid(self, job: JobOffer) -> bool:
        if not job.url or job.url == "N/A" or not job.url.startswith("http"):
            logger.warning(f"Invalid URL format for job '{job.title}': {job.url}")
            return False

        # Check cache first
        if config.validator_cache_enabled and job.url in self.validation_cache:
            cached_result = self.validation_cache[job.url]
            logger.debug(f"Cache hit for {job.url}: {cached_result}")
            return cached_result

        try:
            logger.info(f"Validating job '{job.title}' at URL: {job.url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            # HTTP request with configurable timeout
            async with httpx.AsyncClient(timeout=config.validator_timeout) as client:
                response = await client.get(job.url, headers=headers)

            # Check for dead links (404, 500, etc.)
            if response.status_code >= 400:
                logger.warning(
                    f"HTTP Error {response.status_code} when accessing {job.url}"
                )
                if config.validator_cache_enabled:
                    self.validation_cache[job.url] = False
                return False

            # Extract and analyze text content
            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()

            text_content = soup.get_text(separator=" ", strip=True)
            text_to_analyze = text_content[: config.validator_content_max_chars]

            # Retry logic for LLM call
            result = await self._invoke_llm_with_retry(job.title, text_to_analyze)

            if not result or not result.is_active:
                reason = result.reason if result else "Unknown"
                logger.info(f"Job '{job.title}' is expired/inactive. Reason: {reason}")
                if config.validator_cache_enabled:
                    self.validation_cache[job.url] = False
                return False

            logger.info(f"Job '{job.title}' is active.")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = True
            return True

        except httpx.TimeoutException:
            logger.error(f"Timeout ({config.validator_timeout}s) for {job.url}")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = False
            return False
        except httpx.HTTPError as e:
            logger.error(f"Request failed for {job.url}: {str(e)}")
            if config.validator_cache_enabled:
                self.validation_cache[job.url] = False
            return False
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
