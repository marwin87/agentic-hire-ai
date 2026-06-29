import asyncio
from typing import Any, cast
from src.config.settings import config
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from langchain_core.tools import tool
from loguru import logger

# Cap concurrent Chromium instances — each launch costs ~150MB RAM and 1-2s startup.
# Scout calls scrape sequentially today, but this guard protects against future
# parallelisation or concurrent users exhausting system resources.
_BROWSER_SEM = asyncio.Semaphore(config.scraper_browser_concurrency)

_JOB_PATH_SIGNALS: list[str] = [
    "job",
    "offer",
    "vacancy",
    "position",
    "career",
    "oferta",
    "praca",
    "ogloszenie",
]
_MIN_JOB_LINKS = config.scraper_min_job_links
_PAGE_TIMEOUT_MS = config.scraper_page_timeout_ms
_JS_RENDER_WAIT_MS = config.scraper_js_render_wait_ms

# Protocol constants shared with scout.py — single source of truth for output prefixes.
JOB_LINKS_PREFIX = "JOB_LINKS:"
JOB_POSTING_PREFIX = "Title:"
# User-Agent sourced from config — shared with job_validator to avoid version drift.
_USER_AGENT = config.scraper_user_agent

_JSON_LD_JS = """() => {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
        try {
            const d = JSON.parse(s.textContent || '');
            if (Array.isArray(d)) {
                for (const item of d) {
                    if (item && item['@type'] === 'JobPosting') return item;
                }
            } else if (d && d['@type'] === 'JobPosting') {
                return d;
            }
        } catch (e) {}
    }
    return null;
}"""

_JOB_LINKS_JS = """(keywords) => {
    const seen = new Set();
    const links = [];
    for (const a of document.querySelectorAll('a[href]')) {
        const href = a.href;
        if (!href || !href.startsWith('http')) continue;
        try {
            const path = new URL(href).pathname.replace(/\\/$/, '');
            const segments = path.split('/').filter(Boolean);
            const hasJobSignal = segments.length >= 2 &&
                segments.some(seg => keywords.some(kw => seg.toLowerCase().includes(kw)));
            if (hasJobSignal) {
                const clean = href.split('?')[0].split('#')[0];
                if (!seen.has(clean)) {
                    seen.add(clean);
                    links.push(clean);
                }
            }
        } catch (e) {}
    }
    return links;
}"""


def _format_job_posting(data: dict[str, Any], url: str) -> str:
    title = str(data.get("title", ""))
    company = ""
    org = data.get("hiringOrganization", {})
    if isinstance(org, dict):
        company = str(org.get("name", ""))
    description = str(data.get("description", ""))[
        : config.scraper_description_max_chars
    ]
    date_posted = str(data.get("datePosted", ""))
    valid_through = str(data.get("validThrough", ""))
    location = ""
    job_loc = data.get("jobLocation", {})
    if isinstance(job_loc, dict):
        addr = job_loc.get("address", {})
        if isinstance(addr, dict):
            location = str(addr.get("addressLocality", ""))
    salary = ""
    salary_info = data.get("baseSalary", {})
    if isinstance(salary_info, dict):
        salary_val = salary_info.get("value", {})
        if isinstance(salary_val, dict):
            min_val = salary_val.get("minValue", "")
            max_val = salary_val.get("maxValue", "")
            currency = str(salary_info.get("currency", ""))
            if min_val and max_val:
                salary = f"{min_val}-{max_val} {currency}".strip()

    lines = [f"{JOB_POSTING_PREFIX} {title}", f"Company: {company}"]
    if location:
        lines.append(f"Location: {location}")
    if date_posted:
        lines.append(f"DatePosted: {date_posted}")
    if valid_through:
        lines.append(f"ValidThrough: {valid_through}")
    if salary:
        lines.append(f"Salary: {salary}")
    lines.append(f"URL: {url}")
    lines.append(f"Description: {description}")
    return "\n".join(lines)


@tool
async def scrape_webpage_tool(url: str) -> str:
    """
    Fetches and extracts content from a webpage using a real browser (Playwright/Chromium).
    Handles JavaScript-rendered pages (SPAs). Returns one of:
    - Structured job data (Title/Company/Description) if Schema.org JobPosting markup is found.
    - 'JOB_LINKS:\\n<url1>\\n<url2>\\n...' if a job listing page is detected (3+ job links found).
    - Plain rendered text content as a fallback.
    - 'Error: <description> at <url>' if the page cannot be accessed.
    """
    logger.debug(f"[SCRAPE] Rendering page: {url}")
    try:
        async with _BROWSER_SEM, async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=_USER_AGENT)
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=_PAGE_TIMEOUT_MS
                )
                await page.wait_for_timeout(_JS_RENDER_WAIT_MS)

                # 1. Try JSON-LD extraction
                json_ld = cast(
                    dict[str, Any] | None,
                    await page.evaluate(_JSON_LD_JS),
                )
                if json_ld:
                    logger.debug(f"[SCRAPE] JSON-LD JobPosting found at {url}")
                    return _format_job_posting(json_ld, url)

                # 2. Try listing page detection
                job_links = cast(
                    list[str],
                    await page.evaluate(_JOB_LINKS_JS, _JOB_PATH_SIGNALS) or [],
                )
                if len(job_links) >= _MIN_JOB_LINKS:
                    logger.debug(
                        f"[SCRAPE] Listing page at {url}: {len(job_links)} job links found"
                    )
                    return f"{JOB_LINKS_PREFIX}\n" + "\n".join(job_links)

                # 3. Text fallback
                logger.debug(f"[SCRAPE] Text fallback for {url}")
                text = await page.inner_text("body")
                return text[: config.scraper_text_max_chars]

            finally:
                await browser.close()

    except PlaywrightTimeoutError:
        logger.warning(f"[SCRAPE] Timeout after {_PAGE_TIMEOUT_MS}ms at {url}")
        return f"Error: page timed out after {_PAGE_TIMEOUT_MS // 1000}s at {url}"
    except PlaywrightError as e:
        logger.warning(f"[SCRAPE] Playwright error at {url}: {e}")
        return f"Error: {e} at {url}"
    except Exception as e:
        logger.error(
            f"[SCRAPE] Unexpected error at {url}: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return f"Error: {type(e).__name__} at {url}"
