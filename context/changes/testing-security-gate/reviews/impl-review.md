<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Security Gate Implementation Plan

- **Plan**: context/changes/testing-security-gate/plan.md
- **Scope**: All Phases (1, 2, 3) of 3
- **Date**: 2026-06-07
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 2 warnings, 2 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Automated Verification Results

- ✅ `uv run mypy src/` — clean (40 files)
- ✅ `uv run pytest tests/unit/test_security_gate.py -v` — 4/4 passed
- ✅ `uv run pytest` — 210 passed, 3 skipped

## Findings

### F1 — cv.py ValueError branch still exposes str(e) in ingestion_error

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: src/api/routes/cv.py:55
- **Detail**: ValueError branch stores str(e) in cv_file.ingestion_error which flows to the client via GET /api/cv/status. Plan explicitly scoped this out as "LLM rejection reasons, not secrets." The sibling Exception branch correctly uses a static string. Inconsistency means future ValueErrors with provider text would leak.
- **Fix**: Fix A — documented as accepted risk: added comment at line 55 marking str(e) as intentional (LLM-generated user-safe rejection reason).
- **Decision**: FIXED via Fix A (accepted risk, documented in code)

### F2 — Redundant get_secret_value() + SecretStr() rewrap across 3 files

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: src/agents/agents.py:30-34, src/utils/__init__.py:22-26, src/api/routes/cv.py:206-209
- **Detail**: All three call sites unwrapped Optional[SecretStr] to plain string then re-wrapped into SecretStr for the LLM constructor. Unnecessary — ChatOpenAI/OpenAIEmbeddings accept Optional[SecretStr] directly.
- **Fix**: Replaced all three blocks with `api_key: SecretStr | None = config.openrouter_api_key`. mypy and tests pass.
- **Decision**: FIXED

### F3 — test_500_handler is a pre-condition lock, not a new-fix regression guard

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: tests/unit/test_security_gate.py:108
- **Detail**: test_500_handler_hides_exception_in_production_mode would pass without any change in this commit — it locks pre-existing behavior in the global exception handler, not a regression guard for this commit's fixes.
- **Fix**: Add a one-line comment clarifying it's a pre-condition lock.
- **Decision**: SKIPPED

### F4 — dev_password hardcoded in settings.py default value (pre-existing)

- **Severity**: OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: src/config/settings.py:76
- **Detail**: database_url default embeds dev_password in source code. Pre-existing; the SecretStr migration correctly wrapped it. SecretStr protects repr but not the source value.
- **Fix**: Added "Dev-only default — MUST be overridden via AGENTIC_HIRE_DATABASE_URL in non-dev envs" comment. Lesson recorded in context/foundation/lessons.md.
- **Decision**: FIXED + ACCEPTED-AS-RULE: Dev credentials in source-code defaults
