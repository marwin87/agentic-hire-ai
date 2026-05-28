<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Docker Compose Hardening (F-05)

- **Plan**: context/changes/docker-compose-hardening/plan.md
- **Scope**: All Phases (1–5)
- **Date**: 2026-05-28
- **Verdict**: NEEDS ATTENTION (resolved during triage)
- **Findings**: 1 critical | 4 warnings | 4 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | FAIL |
| Architecture | WARNING |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Findings

### F1 — Production overlay does not remove dev bind mounts

- **Severity**: ❌ CRITICAL
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Safety & Quality / Plan Adherence
- **Location**: docker-compose.prod.yml:20-21
- **Detail**: Docker Compose list-append semantics mean the prod overlay volumes section added ./data/cv but all 6 dev bind mounts from the base (src, ui, alembic, main.py, ui.py, data/cv) remained. Source code was still live-mounted in production containers.
- **Decision**: FIXED via Fix A — source bind mounts moved to new `docker-compose.dev.yml`; base `docker-compose.yml` is now production-clean (only data/cv mount).

### F2 — AGENTIC_HIRE_LOG_LEVEL and AGENTIC_HIRE_ENVIRONMENT silently ignored

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Architecture
- **Location**: src/config/settings.py (cross-check with docker-compose.prod.yml)
- **Detail**: Both variables were set in compose files and documented but not in AppConfig. pydantic-settings silently dropped them via extra="ignore". App always ran at DEBUG level regardless of LOG_LEVEL=INFO in production.
- **Decision**: FIXED — added `log_level: str` and `environment: str` fields to AppConfig; wired `log_level` into `setup_logging()` signature; updated `main.py` caller.

### F3 — JWT secret has a known fallback value in docker-compose.yml

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: docker-compose.yml:47
- **Detail**: `${AGENTIC_HIRE_JWT_SECRET_KEY:-dev_secret_key_change_in_production}` — the fallback satisfies the entrypoint non-empty check, allowing startup with a publicly-known JWT secret.
- **Decision**: FIXED — removed fallback; now `${AGENTIC_HIRE_JWT_SECRET_KEY}` (empty string if unset → entrypoint catches it).

### F4 — Alembic exit-code check is dead code under set -e

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: docker-entrypoint.sh:55-59
- **Detail**: `set -e` active from line 2; if alembic fails, bash exits before reaching `if [ $? -eq 0 ]`. The else "continuing..." message was unreachable and misleading.
- **Decision**: FIXED — removed dead if/else block; rely on set -e for failure handling.

### F5 — "Up" status grep won't match Docker Compose V2 output in CI

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: .github/workflows/ci.yml:131-132
- **Detail**: Docker Compose V2 uses "running" not "Up" in STATUS column; grep was a no-op on ubuntu-latest.
- **Decision**: FIXED — replaced `grep -q " Up "` with `docker compose ps --status=running -q | grep -q .`

### F6 — DATABASE_URL sed parsing is brittle

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: docker-entrypoint.sh:27-28
- **Detail**: sed regexes for extracting host/port break on passwords containing digits + slash.
- **Decision**: FIXED — replaced with Python urlparse one-liners.

### F7 — JSON + plain-text sinks ran simultaneously

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Architecture
- **Location**: src/config/logging.py
- **Detail**: Both sinks active when JSON mode enabled, producing interleaved output.
- **Decision**: FIXED as part of F2 — plain-text sink now gated on `not json_logs`.

### F8 — No-zombies test checks host ps, not container processes

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/integration/test_graceful_shutdown.py:82-88
- **Detail**: `ps aux | grep uvicorn` on host; Docker processes are invisible there — test passed vacuously.
- **Decision**: FIXED — replaced with `docker top agentic-hire-api` to check container-internal processes.

### F9 — CI silently ignores 4 test files with no explanation

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: .github/workflows/ci.yml:64-68
- **Detail**: 3 of 4 ignored files don't exist; `test_api_endpoints.py` passes fine without live DB and was unnecessarily excluded.
- **Decision**: FIXED — removed dead --ignore paths; `test_api_endpoints.py` restored to test run (180 tests pass); only `tests/integration` excluded with an explanatory comment.
