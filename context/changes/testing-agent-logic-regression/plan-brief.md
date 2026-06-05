# Agent Logic Regression Tests — Plan Brief

> Full plan: `context/changes/testing-agent-logic-regression/plan.md`

## What & Why

Close the three Phase 2 test gaps from `context/foundation/test-plan.md`. The validator, rescout edge, and RAG retrieval paths all have untested failure modes that would allow silent wrong behaviour in production: a live-but-expired job reaching the orchestrator, a rescout loop terminating one step too early, or CV context coming back from the wrong domain.

## Starting Point

Phase 1 (data integrity) is archived. Its DB fixture pattern — real PostgreSQL, SAVEPOINT isolation, two-user fixtures in `tests/integration/conftest.py` — is directly reusable. Existing unit tests in `test_validator_async.py` and `test_graph.py` cover the happy paths and main branches, but miss the specific failure-mode scenarios the test-plan flagged.

## Desired End State

Running `uv run pytest tests/test_validator_async.py tests/test_graph.py tests/integration/test_rag_retrieval.py -v` passes green. Each risk has at least one test that would catch the failure the test-plan described — not just a path-exists check.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Risk #4 phrase coverage | Parametrize 5 known expiration phrases | Documents which phrase classes the system handles and catches phrase-specific regressions | Plan |
| Risk #4 retry exhaustion | Test all-retries-fail path (None return) | The failure mode that causes false negatives in production is LLM unavailability, not success | Plan |
| Risk #5 boundary scope | Off-by-one for both scout_runs and valid_jobs + deduplication reducer | Both boundaries and the reducer were explicitly called out as missing in research | Plan |
| Risk #6 proof approach | Domain vs. decoy chunk pair with limit=1 | Asserting the relevant chunk wins over an irrelevant one proves semantic discrimination, not just retrieval | Plan |
| Risk #6 embeddings | Fake deterministic orthogonal vectors | No API key needed; deterministic; follows AGENTS.md no-real-network-calls rule | Plan |
| Risk #6 test target | CVEmbeddingRepository.search_by_user_and_query directly | get_context_async creates its own session internally, making real_session injection awkward; the risk lives in the SQL query | Plan |
| File organisation | Augment existing files + one new integration file | Co-locates tests with their subjects; follows project layout | Plan |

## Scope

**In scope:**
- `tests/test_validator_async.py` — parametrized phrase tests + retry exhaustion test
- `tests/test_graph.py` — off-by-one boundary tests + deduplication reducer test
- `tests/integration/test_rag_retrieval.py` — new file, pgvector cosine-distance discrimination test

**Out of scope:**
- Vision LLM / OCR pipeline (bypassed — chunks inserted directly)
- Full `CVVectorManager.get_context_async` chain
- Risk #3 (streaming resilience) — Phase 3
- Risk #7 (secret leak) — Phase 4
- CI configuration

## Architecture / Approach

Three self-contained phases, each touching one test file. No production code changes. Phases 1 and 2 augment existing unit test files with targeted gap-fills. Phase 3 creates a new integration test that inserts two `CVEmbedding` rows with orthogonal 1536-dim vectors into the real test DB, queries with `limit=1`, and asserts the domain-relevant chunk wins.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Validator false-negative tests | 5 parametrized phrase tests + retry exhaustion in test_validator_async.py | Mock setup for HTTP-200 + LLM path must match actual httpx mock pattern used elsewhere in the file |
| 2. Rescout boundary tests | 3 boundary/reducer tests in test_graph.py | config.max_scout_runs may be loaded differently in test context — verify value is deterministic |
| 3. RAG relevance integration | New test_rag_retrieval.py with real pgvector | pgvector cosine_distance on unit vectors must rank correctly; verify flush-before-query pattern matches Phase 1 |

**Prerequisites:** Phase 1 DB fixture (archived, reusable). PostgreSQL + pgvector running (same requirement as existing integration tests).  
**Estimated effort:** ~1 session across 3 phases.

## Open Risks & Assumptions

- `config.max_scout_runs` must be a known constant in test context for off-by-one assertions to be deterministic — verify with `from src.config.settings import config` before writing the test.
- pgvector's `cosine_distance` with normalised orthogonal unit vectors should rank software chunk first; if the DB normalises vectors differently, the assertion could be flaky.

## Success Criteria (Summary)

- All three targeted pytest commands pass green after each phase.
- Each new test would catch its named failure mode if the production code broke.
- `uv run pytest tests/integration/ -v` shows no regressions against Phase 1 tests.
