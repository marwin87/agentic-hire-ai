# Scout Scraping Upgrade — Plan Brief

> Full plan: `context/changes/scout-scraping-upgrade/plan.md`

## What & Why

The Scout agent's scraping is broken for modern job portals: `httpx` GET + BeautifulSoup returns empty HTML shells from React SPA job boards, and even when content is retrieved it's a listing-page wall-of-text rather than structured individual job data. This upgrade replaces the scraper with Playwright-based rendering and adds Schema.org JSON-LD extraction so Scout gets real, structured job data instead of garbage.

## Starting Point

`src/tools/scrape.py` is 35 lines — a plain `httpx` GET feeding into BeautifulSoup text extraction, returning up to 10 000 chars of whatever the HTTP response body contains. `playwright` is not in the dependency tree and Chromium is not in the Docker image.

## Desired End State

`scrape_webpage_tool` launches headless Chromium, waits for JavaScript to finish rendering, extracts `JobPosting` Schema.org data when present, and returns a `JOB_LINKS:` sentinel when it detects a listing page so Scout can drill into each individual URL. The Scout agent's LLM receives structured job content instead of SPA shells, producing complete `found_jobs` entries.

## Key Decisions Made

| Decision | Choice | Why |
|---|---|---|
| Rendering engine | Playwright-only (no httpx fallback) | One code path; httpx fast-path heuristics are fragile and SPA portals are the majority of targets |
| Tool return type | Sentinel string (`JOB_LINKS:\n...`) | `ToolMessage.content` is a string; LLM handles free-form output; zero interface change |
| Browser lifecycle | One browser per tool call | Stateless, safe for concurrent calls; startup cost (~1-2s) is acceptable given rate-limit delay |
| Two-stage logic owner | Tool detects listing pages, returns job links | Tool is self-contained; Scout LLM loop already handles multi-call flows |
| Anti-bot strategy | Return error string, let Scout retry | Avoids arms race; Scout's rescout loop handles low job counts |
| Testing | Mocked unit tests (no real Chromium in CI) | Consistent with existing `unittest.mock` pattern; fast; covers all code paths |
| Scout prompt scope | Targeted update only (Step 2) | Limits blast radius; search query changes are a separate concern |
| Playwright timeout | 30 seconds | Balances real-world SPA render times against runaway waits |

## Scope

**In scope:**
- Full rewrite of `src/tools/scrape.py` (Playwright, JSON-LD, listing detection, sentinel return)
- `pyproject.toml` — add `playwright>=1.40.0`, remove `beautifulsoup4` if unused elsewhere
- `Dockerfile` — Chromium install in runtime stage
- `src/agents/scout.py` — targeted Step 2 prompt update for `JOB_LINKS:` handling
- `tests/tools/test_scrape.py` — 5 mocked unit tests

**Out of scope:**
- Portal-specific API clients (justjoin.it, nofluffjobs)
- Search query crafting in Scout prompt
- Anti-bot stealth / UA rotation
- Integration tests with real Chromium in CI

## Architecture / Approach

`scrape_webpage_tool` becomes a three-stage pipeline: (1) Playwright renders the page in headless Chromium with a 30s timeout; (2) JSON-LD extraction looks for `<script type="application/ld+json">` with `@type: "JobPosting"` and returns structured text if found; (3) if no JSON-LD, count anchor links matching job-URL path patterns — if ≥3 found, return `JOB_LINKS:\n<urls>`; otherwise return cleaned text. Scout's LLM loop calls the tool again on each returned URL when it sees the sentinel.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Core Scraper Rewrite | Working Playwright tool with JSON-LD + listing detection | JSON-LD absent on target portals → falls back to text (still better than SPA shell) |
| 2. Docker Infrastructure | Docker image builds with Chromium available | ~300MB image size increase |
| 3. Scout Prompt Integration | LLM correctly follows `JOB_LINKS:` with follow-up scrapes | LLM ignores sentinel if prompt phrasing is unclear |
| 4. Unit Tests | All code paths covered with mocked tests | Mocks don't catch real rendering failures (acceptable; manual testing covers this) |

**Prerequisites:** OrioSearch running locally for end-to-end manual tests; Docker daemon available for Phase 2 verification  
**Estimated effort:** ~1-2 sessions across 4 phases

## Open Risks & Assumptions

- Some portals embed JSON-LD only on individual job pages, not on listing pages — listing detection heuristic (anchor link counting) may classify unusual pages incorrectly; Scout's rescout loop mitigates low job counts
- Playwright's `networkidle` wait may timeout on very slow portals — error string returned, Scout continues with other results
- Docker image grows by ~300MB — acceptable for this use case but worth tracking

## Success Criteria (Summary)

- `scrape_webpage_tool` returns `JOB_LINKS:` sentinel when pointed at a portal listing page (e.g. justjoin.it/job-offers/python)
- Individual job page scrapes return structured title/company/description content
- Full Scout run produces `found_jobs` with complete job data from SPA portals
