---
change_id: scout-scraping-upgrade
title: Scout scraping upgrade
status: archived
created: 2026-05-29
updated: 2026-05-29
archived_at: 2026-05-29T15:04:00Z
---

## Notes

<!-- Free-form notes for this change: links, ad-hoc context, decisions that don't belong in research/frame/plan. -->

Here's a detailed breakdown of what this feature involves:

---
Problem Statement

Current flow breaks at two points:
1. OrioSearch returns portal/listing page URLs (e.g. justjoin.it/job-offers/python) — not individual job pages
2. scrape_webpage_tool uses BeautifulSoup which does a plain HTTP GET — modern job portals are React/Vue SPAs that
return an empty JS shell, so the scraped content is useless

Result: Scout feeds the LLM garbage → parsed JobOffer objects are missing or wrong.


---
Solution: Three-layer fix

Layer 1 — Playwright replaces BeautifulSoup in scrape_webpage_tool

Instead of a raw HTTP request, launch a headless Chromium browser, navigate to the URL, wait for JavaScript to finish
rendering (networkidle state), then extract the fully-rendered DOM. This makes scraping work on any modern web app
generically.

What changes: src/tools/scrape.py — replace httpx + BeautifulSoup with async_playwright.

---
Layer 2 — JSON-LD extraction added to scrape_webpage_tool

After Playwright renders the page, before doing any text extraction, look for <script type="application/ld+json"> tags
in the DOM. These contain structured JobPosting data in Schema.org format — a web standard that most job portals and
company career pages implement for Google job indexing. It looks like:

{
"@type": "JobPosting",
"title": "Senior Python Developer",
"hiringOrganization": { "name": "Acme Corp" },
"description": "...",
"datePosted": "2026-05-20",
"validThrough": "2026-06-20",
"jobLocation": { "address": { "addressLocality": "Warsaw" } },
"baseSalary": { "value": { "minValue": 15000, "maxValue": 22000 } }
}

If found, return this as structured data immediately — no LLM text parsing needed for basic fields. If not found, fall
back to cleaned text extraction (current behavior).

What changes: src/tools/scrape.py — add extract_json_ld() function, call it before text fallback, return structured
result when available.

---
Layer 3 — Two-stage scraping: listing page → individual job URLs

When the scraped page is a listing page (portal search results), extract all individual job post links from the
rendered DOM, return them as a list, and let Scout's LLM loop scrape each one individually. This replaces the current
single-pass scrape that tries to extract multiple jobs from one messy page.

URL classification heuristics — a simple function to detect whether a URL is an individual job page or a listing page:
- Individual job signals: path contains /job/, /offer/, /vacancy/, /oferta/, /careers/ + a slug or numeric ID at the
end
- Listing page signals: path is shallow (e.g. /jobs, /job-offers, /search), or root domain

What changes:
- src/tools/scrape.py — add URL classifier, add link extraction logic, change return type to distinguish "job_posting"
vs "job_links" vs "text_content"
- src/agents/scout.py — update system prompt to instruct LLM to follow up on returned job link lists by scraping each
one

---
Files changed

┌─────────────────────┬───────────────────────────────────────────────────────────────────────────────────────┐
│        File         │                                        Change                                         │
├─────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ src/tools/scrape.py │ Full refactor: Playwright render, JSON-LD extraction, URL classifier, two-stage logic │
├─────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ src/agents/scout.py │ System prompt update: guide LLM to handle "job_links" returns, prefer deep URLs       │
├─────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ pyproject.toml      │ Add playwright dependency                                                             │
├─────────────────────┼───────────────────────────────────────────────────────────────────────────────────────┤
│ Dockerfile          │ Add playwright install chromium --with-deps step                                      │
└─────────────────────┴───────────────────────────────────────────────────────────────────────────────────────┘

---
Before / After data flow

Before:
search("python developer warsaw")
→ ["justjoin.it/job-offers/python", ...]
→ BeautifulSoup HTTP GET → empty SPA shell
→ LLM gets: "<div id='app'></div>"
→ 0 parsed jobs

After:
search("python developer senior warsaw apply requirements")
→ ["justjoin.it/job-offers/python", "nofluffjobs.com/job/slug-123", ...]
→ Playwright render → full DOM
→ URL classifier: "listing page"
→ extract job links: ["/offers/python-dev-acme-123", "/offers/backend-xyz-456", ...]
→ scrape each individually
→ JSON-LD found → structured JobPosting data
→ clean JobOffer objects, no LLM guesswork

---
Risks / Considerations

- Playwright cold start — first launch of Chromium takes ~1-2s. Subsequent pages in the same session are fast.
Consider reusing browser instance across tool calls within one Scout run.
- Anti-bot detection — some portals block headless browsers. Mitigation: set realistic User-Agent, avoid too-fast
requests (rate limiting already in place via scout_rate_limit_delay).
- Docker image size — Chromium adds ~300MB to the image. Worth documenting in docker-practices.md.
- JSON-LD not always present — company career pages built on custom CMS may not have it. Text fallback remains for
those cases.
- Return type change in scrape_webpage_tool — the tool currently returns a plain string. Returning structured data
means the LLM prompt needs to know how to interpret the new format. The tool docstring and Scout system prompt both
need updating.
- Tests — existing tests/tools/ mocks will need updating to account for Playwright and the new return shapes.

---
This is a meaningful refactor of scrape.py (the most impacted file) plus lighter touches on Scout's prompt and the
Docker setup. Want me to proceed with implementation?
