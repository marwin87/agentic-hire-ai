# Scout Scraping Upgrade Implementation Plan

## Overview

Replace `scrape_webpage_tool`'s BeautifulSoup/httpx scraper with a Playwright-based renderer that extracts structured job data via JSON-LD and detects listing pages, returning individual job URLs via a sentinel string. Scout's system prompt is updated to handle the new return format. This fixes the core quality failure: modern SPA job portals return empty HTML shells to httpx GET requests, so BeautifulSoup extracts nothing useful.

## Current State Analysis

`src/tools/scrape.py` (35 lines) performs a plain `httpx` GET followed by BeautifulSoup text extraction. Modern job portals (justjoin.it, nofluffjobs.com) are React SPAs — they return a near-empty `<div id="root"></div>` to an HTTP GET, so BeautifulSoup extracts nothing useful. Even static portals return listing pages rather than individual job postings, giving the LLM a wall of mixed text to parse into jobs.

`src/agents/scout.py:27` binds `scrape_webpage_tool` to the LLM. The tool's return value is passed as `ToolMessage.content` (a string). Scout's system prompt Step 2 instructs the LLM to scrape portal pages without awareness that results may be listing pages requiring a follow-up scrape.

No tool tests exist in `tests/tools/` — the test suite covers only graph logic and utilities.

## Desired End State

`scrape_webpage_tool` renders pages via headless Chromium, extracts `JobPosting` Schema.org structured data when present, and returns a sentinel-delimited list of individual job URLs when it detects a listing page. Scout's LLM calls the tool again on each returned URL to get real job content. The result: `found_jobs` populated with complete title/company/description data instead of empty or mixed-text scrapes.

**Verification**: Run Scout agent against a known SPA portal (e.g. justjoin.it) and confirm `found_jobs` contains complete `JobOffer` objects with real job data.

### Key Discoveries:

- `src/tools/scrape.py:8` — `scrape_webpage_tool` return type is `str`; this is preserved — no interface change at the tool-binding layer
- `src/agents/scout.py:176-185` — scrape result is passed as `ToolMessage.content=str(raw_results)`; the new sentinel format must be parseable as-is by the LLM without JSON deserialisation
- `pyproject.toml:7-35` — `playwright` not listed; `beautifulsoup4>=4.14.3` is listed and can be removed once scrape.py no longer imports it
- `Dockerfile:24-61` — multi-stage build; `.venv` is copied from builder to runtime, but Playwright browser binaries (`~/.cache/ms-playwright/`) are NOT inside `.venv` — Chromium must be installed in the **runtime** stage explicitly
- `context/foundation/lessons.md` — narrow exception types: `TimeoutError` and `Error` from Playwright are recoverable; bare `except Exception` must not be the sole catch

## Addendum — Unplanned Scope Delivered in Same Commit

The following work was discovered and implemented during the session beyond the original 4-phase plan. All items were explicitly discussed and approved:

- **Live streaming UI** (`src/api/routes/workflows.py`, `frontend/hooks/useWorkflowStream.ts`, `frontend/app/dashboard/page.tsx`, `frontend/lib/workflow-types.ts`) — streaming endpoint refactored from flat `graph.astream()` to background task + asyncio.Queue; frontend tiles replaced with append-only per-run message log.
- **Progress event queue** (`src/utils/progress.py`) — ContextVar-based queue so any agent can `await emit()` during execution; `src/utils.py` converted to `src/utils/` package.
- **Preferred portals + pre-seed** (`src/config/settings.py`, `src/agents/scout.py`) — configurable portal list; pre-seed loop runs one targeted search per portal before the main LLM loop.
- **Agent emit() calls** (`src/agents/orchestrator.py`, `src/agents/tailor.py`, `src/graph.py`) — live progress messages for each job scored/validated/tailored.
- **OrioSearch search_depth** (`src/tools/search.py`) — added `"search_depth": "advanced"` to the OrioSearch payload.
- **scout_max_iterations** raised from 3 → 10 (`src/config/settings.py`) — needed for two-stage follow-up capacity.

---

## What We're NOT Doing

- Portal-specific API integrations (justjoin.it API, nofluffjobs GraphQL) — potential follow-on
- Search query crafting improvements in Scout's prompt — separate concern, out of this change's blast radius
- Anti-bot stealth techniques (UA rotation, proxy) — return an error string and let Scout retry
- Integration tests with a real Chromium browser in CI — mocked unit tests only

## Implementation Approach

Phase 1 rewrites the tool as the core deliverable and declares the dependency. Phase 2 installs Chromium in the Docker runtime stage. Phase 3 updates Scout's prompt to handle the `JOB_LINKS:` sentinel. Phase 4 adds mocked unit tests covering all code paths.

The sentinel string `JOB_LINKS:\n` was chosen over a structured dict because `ToolMessage.content` is a string, the LLM already handles free-form tool output, and no change is needed at the tool-binding layer in `scout.py:27`.

## Critical Implementation Details

**Playwright browser install in Docker**: The `.venv` is copied from the builder stage, but Playwright browser binaries are written to `~/.cache/ms-playwright/`, not inside `.venv`. The runtime stage must run `RUN /app/.venv/bin/playwright install --with-deps chromium` **after** copying `.venv`. Placing the install only in the builder stage leaves the runtime container without Chromium — the tool will raise `BrowserType.launch: Executable doesn't exist` at runtime.

---

## Phase 1: Core Scraper Rewrite

### Overview

Replace `src/tools/scrape.py` entirely: Playwright renders the page (30s timeout, networkidle wait), JSON-LD extraction runs first, listing page detection with job link extraction runs second, and text extraction is the fallback. Declare `playwright` in `pyproject.toml` and sync the lock file.

### Changes Required:

#### 1. Tool implementation

**File**: `src/tools/scrape.py`

**Intent**: Rewrite using `async_playwright` to launch headless Chromium, navigate to the URL, wait for `networkidle`, then extract content. Remove all `httpx` and `beautifulsoup4` imports. Follow `lessons.md`: catch `playwright.async_api.TimeoutError` and `playwright.async_api.Error` as recoverable and return a descriptive error string; catch unexpected `Exception` separately with `exc_info=True` logging. Do not re-raise — tool errors are recoverable by the Scout loop.

**Contract**: Function signature stays `async def scrape_webpage_tool(url: str) -> str`. Three return shapes the LLM and Scout prompt depend on:

```
# Individual job page with JSON-LD (Schema.org JobPosting found):
"Title: Senior Python Developer\nCompany: Acme Corp\nDescription: ...\nDatePosted: 2026-05-01\nURL: https://..."

# Listing / portal page (≥3 individual job links detected, no JSON-LD):
"JOB_LINKS:\nhttps://portal.com/jobs/slug-123\nhttps://portal.com/jobs/slug-456\n..."

# Text fallback (no JSON-LD, <3 job links) or error:
"<rendered text content up to 10 000 chars>"
"Error: <description> at <url>"
```

JSON-LD extraction: iterate `<script type="application/ld+json">` tags; parse JSON; if `@type == "JobPosting"` (or a list containing it), format the relevant fields as the structured string above.

Listing detection: after JSON-LD fails, collect `<a href>` anchors whose paths contain job-page signals (`/job/`, `/offer/`, `/vacancy/`, `/position/`, `/careers/`, `/oferta/`) and have a slug or ID-like last segment. If ≥3 such links are found, return the `JOB_LINKS:` sentinel. Otherwise fall back to `get_text()` extraction capped at 10 000 chars.

#### 2. Dependency declaration

**File**: `pyproject.toml`

**Intent**: Add `playwright` to the `[project]` dependencies list. Check whether any other file in `src/` imports `beautifulsoup4` (`bs4`); if `scrape.py` was the sole consumer, remove the `beautifulsoup4` entry. Run `uv sync` to regenerate `uv.lock`.

**Contract**: Add `"playwright>=1.40.0"` in the dependencies array. After syncing, `uv.lock` reflects the addition.

### Success Criteria:

#### Automated Verification:

- `uv sync` completes without error
- `uv run python -c "from src.tools.scrape import scrape_webpage_tool; print('ok')"` exits 0
- `uv run mypy src/tools/scrape.py` — no errors
- `uv run black src/tools/scrape.py --check` — no diff

#### Manual Verification:

- `uv run python -c "import asyncio; from src.tools.scrape import scrape_webpage_tool; print(asyncio.run(scrape_webpage_tool.ainvoke({'url': 'https://justjoin.it/job-offers/python'})))"` — output starts with `JOB_LINKS:` and contains individual job URLs
- Run the same against a known individual job page with Schema.org markup — output contains `Title:` / `Company:` fields
- Run against an unreachable URL — output starts with `Error:`

**Implementation Note**: After Phase 1 automated verification passes, pause for manual verification before proceeding to Phase 2.

---

## Phase 2: Docker Infrastructure

### Overview

Install Playwright's Chromium binary and its system dependencies in the Dockerfile runtime stage so the containerised app can launch a browser.

### Changes Required:

#### 1. Runtime stage browser install

**File**: `Dockerfile`

**Intent**: In the runtime stage, after `COPY --from=builder /app/.venv /app/.venv`, run `playwright install --with-deps chromium` using the virtualenv's binary. This installs Chromium (~300MB) and required system libraries (libnss3, libdrm, etc.) into the runtime image.

**Contract**: Add one `RUN` line to the runtime stage:

```dockerfile
RUN /app/.venv/bin/playwright install --with-deps chromium
```

No changes to the builder stage. This line must come **after** the `.venv` copy so the binary exists.

### Success Criteria:

#### Automated Verification:

- `docker build -t agentic-hire-ai .` completes without error
- `docker run --rm agentic-hire-ai python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('ok')"` exits 0

#### Manual Verification:

- Container starts normally; scrape tool can render a URL when invoked via `docker exec` or a CLI run inside the container

**Implementation Note**: After Phase 2 automated verification passes, pause for manual smoke test before proceeding.

---

## Phase 3: Scout Prompt Integration

### Overview

Update Scout's system prompt to explain the `JOB_LINKS:` sentinel so the LLM knows to follow up on listing page responses by scraping each individual URL.

### Changes Required:

#### 1. System prompt Step 2 update

**File**: `src/agents/scout.py`

**Intent**: In the `system_msg` content block (around line 102-117), replace the current Step 2 sentence with an updated version that covers both scrape return shapes. When the tool returns plain job content, proceed to Step 3. When it returns a `JOB_LINKS:` sentinel, call `scrape_webpage_tool` on each listed URL individually before proceeding. Keep Steps 1, 3, and 4 unchanged.

**Contract**: Step 2 in the prompt becomes a two-case instruction:

```
Step 2: Use the 'scrape_webpage_tool' to open URLs found in Step 1.
  - If the result contains job content (title, description, company), proceed to Step 3.
  - If the result starts with 'JOB_LINKS:' followed by URLs (one per line), it found a listing page.
    Call 'scrape_webpage_tool' on each of those URLs individually to retrieve the actual job content.
```

### Success Criteria:

#### Automated Verification:

- `uv run mypy src/agents/scout.py` — no errors
- `uv run pytest tests/test_graph.py -v` — all existing tests pass (no regression)

#### Manual Verification:

- Full Scout run (`uv run python main.py`) — confirm Scout makes follow-up scrape calls when a `JOB_LINKS:` response is returned; `found_jobs` count is nonzero with real job content

**Implementation Note**: After Phase 3 automated verification passes, pause for manual end-to-end validation before proceeding.

---

## Phase 4: Unit Tests

### Overview

Write mocked unit tests for `scrape_webpage_tool` covering all four code paths using `unittest.mock` (consistent with the existing test pattern in `tests/test_graph.py`).

### Changes Required:

#### 1. Test file

**File**: `tests/tools/test_scrape.py`

**Intent**: Create 5 async unit tests that patch `playwright.async_api.async_playwright` with `AsyncMock` to avoid real browser launches. Cover: JSON-LD job page, listing page with job links, text fallback, Playwright `TimeoutError`, and unexpected `Exception`. Decorate with `@pytest.mark.asyncio` consistent with `pytest-asyncio>=0.24.0` already in dev deps.

**Contract**: Test IDs and what each asserts:
- `test_json_ld_job_page` — mock page content contains valid `JobPosting` JSON-LD; assert return contains `"Title:"` and `"Company:"`
- `test_listing_page_returns_job_links` — mock page contains ≥3 job anchor links, no JSON-LD; assert return starts with `"JOB_LINKS:\n"`
- `test_text_fallback` — mock page has no JSON-LD and <3 job links; assert return is non-empty text not starting with `"JOB_LINKS:"` or `"Error:"`
- `test_timeout_error` — mock `page.goto` raises `playwright.async_api.TimeoutError`; assert return starts with `"Error:"`
- `test_unexpected_exception` — mock `page.goto` raises `RuntimeError`; assert return starts with `"Error:"`

### Success Criteria:

#### Automated Verification:

- `uv run pytest tests/tools/test_scrape.py -v` — all 5 tests pass
- `uv run mypy tests/tools/test_scrape.py` — no errors

---

## Testing Strategy

### Unit Tests:

- JSON-LD extraction: valid `JobPosting` schema → structured title/company/description string
- Listing page detection: ≥3 matching job anchor links → `JOB_LINKS:` sentinel string
- Text fallback: no JSON-LD, <3 job links → cleaned text ≤10 000 chars
- Timeout error path: `playwright.async_api.TimeoutError` → `"Error: ..."` string
- Unexpected exception path: `RuntimeError` → `"Error: ..."` string

### Manual Testing Steps:

1. Run scrape tool directly against `https://justjoin.it/job-offers/python` — confirm `JOB_LINKS:` response with valid individual job URLs
2. Scrape one of the returned individual URLs — confirm `Title:` / `Company:` fields or readable job text
3. Run full `uv run python main.py` end-to-end — confirm `found_jobs` populated with real job data
4. `docker build` + Chromium smoke test in container

## Performance Considerations

Each Playwright call adds ~1-2s browser cold start + page render time, capped at 30s timeout. Scout's existing `scout_rate_limit_delay` already spaces out tool calls. At `scout_max_iterations=10` with up to 10 scrapes per run, worst-case wall-clock increase is ~20-40s — acceptable for a background job-discovery workflow.

## References

- `src/tools/scrape.py` — file being replaced
- `src/agents/scout.py:102-117` — system prompt block updated in Phase 3
- `src/agents/scout.py:176-185` — ToolMessage construction showing the `str` return contract
- `context/foundation/lessons.md` — exception handling rules applied in Phase 1

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Core Scraper Rewrite

#### Automated

- [x] 1.1 `uv sync` completes without error
- [x] 1.2 `uv run python -c "from src.tools.scrape import scrape_webpage_tool; print('ok')"` exits 0
- [x] 1.3 `uv run mypy src/tools/scrape.py` — no errors
- [x] 1.4 `uv run black src/tools/scrape.py --check` — no diff

#### Manual

- [ ] 1.5 Scrape justjoin.it listing page — output starts with `JOB_LINKS:`
- [ ] 1.6 Scrape an individual job page with JSON-LD — output contains `Title:` / `Company:` fields
- [ ] 1.7 Scrape an unreachable URL — output starts with `Error:`

### Phase 2: Docker Infrastructure

#### Automated

- [ ] 2.1 `docker build -t agentic-hire-ai .` completes without error
- [ ] 2.2 Chromium launch smoke test in container exits 0

#### Manual

- [ ] 2.3 Container starts and scrape tool renders a URL via docker exec

### Phase 3: Scout Prompt Integration

#### Automated

- [x] 3.1 `uv run mypy src/agents/scout.py` — no errors
- [x] 3.2 `uv run pytest tests/test_graph.py -v` — all existing tests pass

#### Manual

- [ ] 3.3 Full Scout run confirms follow-up scrape calls on `JOB_LINKS:` responses
- [ ] 3.4 `found_jobs` populated with real job data after end-to-end run

### Phase 4: Unit Tests

#### Automated

- [x] 4.1 `uv run pytest tests/tools/test_scrape.py -v` — all 5 tests pass
- [x] 4.2 `uv run mypy tests/tools/test_scrape.py` — no errors
