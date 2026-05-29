<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Scout Scraping Upgrade

- **Plan**: `context/changes/scout-scraping-upgrade/plan.md`
- **Scope**: All 4 phases (full plan review)
- **Date**: 2026-05-29
- **Commit**: a806557
- **Verdict**: APPROVED (all warnings resolved during triage)
- **Findings**: 0 critical · 3 warnings · 6 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | WARNING → FIXED |
| Safety & Quality | WARNING → FIXED |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS (automated) · PENDING (manual) |

## Findings

### F1 — Significant unplanned scope in the commit

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW
- **Dimension**: Scope Discipline
- **Location**: plan.md, change.md
- **Detail**: Commit included 7+ extra files beyond the 4-phase plan (live streaming UI, progress queue, preferred portals, emit() calls in all agents, search_depth param). All discussed and approved during session.
- **Fix**: Added Addendum section to plan.md documenting the extra scope.
- **Decision**: FIXED

### F2 — await task in finally blocks server on client disconnect

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/workflows.py:462
- **Detail**: `finally: await task` held the server coroutine until full graph completion even if client disconnected mid-stream.
- **Fix**: Replaced with cancel + asyncio.shield pattern.
- **Decision**: FIXED (Fix A)

### F3 — Rejected jobs double-counted across validate + orchestrator accumulators

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/workflows.py:393–405
- **Detail**: Validation-rejected jobs (score=0.0, never scored) mixed with score-rejected jobs, producing 0% match cards in UI.
- **Fix**: Added guard to skip jobs with match_score==0.0 when building all_job_results.
- **Decision**: FIXED (Fix A)

### F4 — Stale "30s" in timeout error message

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: src/tools/scrape.py:161
- **Detail**: Error message said "30s" but timeout constant is 15000ms.
- **Fix**: Changed to `f"Error: page timed out after {_PAGE_TIMEOUT_MS // 1000}s at {url}"`.
- **Decision**: FIXED

### F5 — Missing cast(str, tool_id) for scrape branch in scout.py

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: src/agents/scout.py:254
- **Detail**: Inconsistent with job_search_tool branch which casts tool_id.
- **Fix**: Added `cast(str, tool_id)` to match the search branch pattern.
- **Decision**: FIXED

### F6 — ContextVar propagation (empirically verified working)

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Architecture
- **Location**: src/utils/progress.py, src/api/routes/workflows.py:337
- **Detail**: Review raised concern about ContextVar propagation into LangGraph-dispatched tasks. Empirically confirmed working — LangGraph awaits node coroutines directly.
- **Fix**: Added explanatory comment in progress.py. Lesson saved to context/foundation/lessons.md.
- **Decision**: FIXED + ACCEPTED-AS-RULE: ContextVar propagation through async coroutine chains

### F7 — workflow_complete uses return instead of break in SSE hook

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: frontend/hooks/useWorkflowStream.ts:139
- **Detail**: `return` instead of `break` could drop buffered events after workflow_complete.
- **Fix**: Changed `return` to `break`.
- **Decision**: FIXED

### F8 — Unplanned search_depth param in OrioSearch payload

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Scope Discipline
- **Location**: src/tools/search.py:17
- **Detail**: `"search_depth": "advanced"` added to payload — not in plan. Intentional improvement.
- **Decision**: SKIPPED

### F9 — No concurrency cap on Playwright browser instances

- **Severity**: 👁 OBSERVATION
- **Impact**: 🏃 LOW
- **Dimension**: Safety & Quality
- **Location**: src/tools/scrape.py:122
- **Detail**: Each scrape spawns a new Chromium with no cap. Sequential today but unprotected for future parallelisation.
- **Fix**: Added `_BROWSER_SEM = asyncio.Semaphore(3)` module-level guard.
- **Decision**: FIXED
