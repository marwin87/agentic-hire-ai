from pydantic import BaseModel, Field


class ScraperMixin(BaseModel):
    """OrioSearch API, Playwright web scraper, and job validator settings."""

    # OrioSearch job-search API
    oriosearch_base_url: str = Field("http://localhost:8000")
    oriosearch_num_results: int = Field(
        10, description="Number of results per OrioSearch query."
    )
    oriosearch_search_depth: str = Field(
        "advanced", description="OrioSearch search depth mode."
    )
    oriosearch_max_retries: int = Field(
        3, description="Max retry attempts for OrioSearch requests."
    )
    oriosearch_retry_delay_s: float = Field(
        1.0, description="Initial retry delay in seconds (doubles each attempt)."
    )
    oriosearch_timeout: float = Field(
        10.0, description="HTTP timeout in seconds for OrioSearch requests."
    )

    # Web scraper (Playwright-based)
    scraper_browser_concurrency: int = Field(
        3, description="Max concurrent Playwright browser instances."
    )
    scraper_page_timeout_ms: int = Field(
        15000, description="Playwright page load timeout in milliseconds."
    )
    scraper_js_render_wait_ms: int = Field(
        2000, description="Wait time in milliseconds for JavaScript rendering."
    )
    scraper_min_job_links: int = Field(
        3, description="Minimum job links on a page to classify it as a listing page."
    )
    scraper_description_max_chars: int = Field(
        5000, description="Max characters extracted from JSON-LD job description."
    )
    scraper_text_max_chars: int = Field(
        10000, description="Max characters returned from plain-text page fallback."
    )

    # Job validator
    validator_timeout: int = Field(
        10, description="HTTP timeout in seconds for job validation requests."
    )
    validator_content_max_chars: int = Field(
        6000, description="Max characters to analyze for expiration detection."
    )
    validator_max_retries: int = Field(
        2, description="Max retries for failed LLM validation calls."
    )
    validator_cache_enabled: bool = Field(
        True, description="Cache job validation results."
    )
    validator_cache_ttl_s: int = Field(
        3600, description="Seconds before a cached validation result expires (1 hour)."
    )

    # Orchestrator / RAG retrieval
    orchestrator_description_snippet_chars: int = Field(
        200, description="Characters of job description used as RAG search query."
    )
    orchestrator_rag_context_chunks: int = Field(
        3, description="Number of CV chunks to retrieve from pgvector per job."
    )
