# Agent Logic Regression Tests Implementation Plan

## Overview

Close the three Phase 2 risk gaps from `context/foundation/test-plan.md`: fill unit-level holes in the existing validator and rescout tests, then add a pgvector integration test that proves semantic relevance discrimination — not just that retrieval returns something.

## Current State Analysis

Phase 1 (data integrity) shipped and is archived. The test patterns it established — real async DB session with SAVEPOINT isolation, two-user fixtures in `tests/integration/conftest.py` — are reusable directly for Phase 2's integration work.

### Key Discoveries

- `deduplicate_seen_jobs` reducer (`src/schema/state.py:31-33`) is a simple `list(set(existing + new))` — directly importable and testable without the full graph.
- `should_rescout` has 4 branches already covered in `test_graph.py`, but no test for `scout_runs == max_scout_runs - 1` (should rescout) nor `valid_jobs == max_offers - 1` (should rescout) — the off-by-one cases.
- `test_validator_async.py` already tests `LLM returns is_active=False`, but not the two-stage path where HTTP returns 200 and the page *body* triggers LLM expiration detection — the production false-negative scenario.
- `_invoke_llm_with_retry` retry exhaustion (all attempts raise, function returns `None`) is untested; `validate_job_with_reason` must degrade gracefully.
- `CVEmbedding` has fields `user_id`, `chunk_text` (Text), `embedding` (Vector(1536)). `CVEmbeddingRepository.search_by_user_and_query` orders by `cosine_distance` ascending — lower = more similar.
- The RAG integration test can target `CVEmbeddingRepository.search_by_user_and_query` directly with `real_session`, bypassing Vision OCR. This is cleaner than routing through `CVVectorManager`, whose `get_context_async` creates its own session internally.

## Desired End State

Three risk coverage gaps are closed:

- **Risk #4**: HTTP-200 + expiration-phrase parametrized tests prove each known phrase class triggers rejection via the LLM path. Retry exhaustion test proves graceful failure when LLM is unavailable.
- **Risk #5**: Off-by-one boundary tests prove `should_rescout` does not terminate early when one job short of target. Deduplication reducer test proves `seen_jobs` stays unique across multi-cycle accumulation.
- **Risk #6**: pgvector integration test proves domain-specific chunk is ranked first over a decoy; the assertion is on `chunk_text` content, not just non-empty list.

Running `uv run pytest tests/test_validator_async.py tests/test_graph.py tests/integration/test_rag_retrieval.py -v` passes green.

### Key Discoveries (test-plan alignment)

- Anti-pattern avoided for Risk #4: only testing 404/410 HTTP case. New tests add HTTP-200 + LLM-phrase path.
- Anti-pattern avoided for Risk #5: only asserting happy path. Boundary tests cover the one-below-limit cases.
- Anti-pattern avoided for Risk #6: asserting only non-empty list. Test uses `limit=1` + domain/decoy chunk pair.

## What We're NOT Doing

- Not testing OrioSearch internal ranking logic (out of scope per test-plan §7).
- Not testing Vision LLM OCR quality (ingest pipeline is bypassed; we insert chunks directly).
- Not testing the full `CVVectorManager.get_context_async` chain — only the repository SQL query that owns the semantic matching risk.
- Not adding CI configuration (planned but not in this phase per test-plan §5).
- Not covering Risk #3 (streaming resilience) or Risk #7 (secret leak) — those are Phases 3 and 4.

## Implementation Approach

Three self-contained phases, each touching one test file. Phases 1 and 2 are augmentations of existing unit test files. Phase 3 creates a new integration test file reusing the Phase 1 DB fixture. No production code changes — test code only.

---

## Phase 1: Risk #4 — Validator False-Negative Tests

### Overview

Add two missing test scenarios to `tests/test_validator_async.py`: (a) parametrized HTTP-200 + expiration-phrase tests proving the two-stage validation path, and (b) LLM retry exhaustion proving graceful failure.

### Changes Required

#### 1. Parametrized expiration-phrase tests

**File**: `tests/test_validator_async.py`

**Intent**: Prove that when an HTTP 200 response body contains a known expiration phrase, the validator invokes the LLM and rejects the job — not just that an already-mocked LLM-inactive case works. This is the production false-negative scenario: job page still loads (200) but posting is closed.

**Contract**: Add a `@pytest.mark.parametrize("phrase", [...])` test with at minimum these five phrases: `"This position has been filled"`, `"Job no longer available"`, `"This posting has expired"`, `"Application period has ended"`, `"Position closed"`. For each: mock `httpx.AsyncClient.get` to return status 200 with the phrase in the response text; mock `self.checker.ainvoke` (the LLM structured-output call) to return `ExpirationCheck(is_active=False, reason=phrase)`. Assert `validate_job_with_reason` returns a result where `is_valid == False`.

#### 2. LLM retry exhaustion test

**File**: `tests/test_validator_async.py`

**Intent**: Prove that when `_invoke_llm_with_retry` exhausts all retry attempts (every LLM call raises), `validate_job_with_reason` returns a graceful invalid result rather than raising or returning a valid result.

**Contract**: Mock HTTP to return 200 with non-expiration body text. Mock `self.checker.ainvoke` to always raise `Exception("LLM unavailable")`. Assert `validate_job_with_reason` returns a result with `is_valid == False`. The test must not raise.

### Success Criteria

#### Automated Verification

- All existing + new tests in `test_validator_async.py` pass: `uv run pytest tests/test_validator_async.py -v`
- Black formatting: `uv run black tests/test_validator_async.py --check`

#### Manual Verification

- Each parametrized phrase case is listed individually in pytest output (not collapsed into one pass).

**Implementation Note**: Pause after Phase 1 for manual confirmation before proceeding.

---

## Phase 2: Risk #5 — Rescout Boundary Tests

### Overview

Add three missing test scenarios to `tests/test_graph.py`: off-by-one boundary for `scout_runs`, off-by-one boundary for `valid_jobs`, and direct `deduplicate_seen_jobs` reducer correctness.

### Changes Required

#### 1. Off-by-one boundary: scout_runs

**File**: `tests/test_graph.py`

**Intent**: Prove `should_rescout` returns `"rescout"` when `scout_runs` is one below the max — i.e., the boundary condition where the existing test only covers `scout_runs == max` (proceed).

**Contract**: Build a state fixture with `scout_runs = config.max_scout_runs - 1`, `valid_jobs = []`, `found_jobs` non-empty. Call `should_rescout(state)` directly. Assert return value is `"rescout"`.

#### 2. Off-by-one boundary: valid_jobs

**File**: `tests/test_graph.py`

**Intent**: Prove `should_rescout` returns `"rescout"` when `valid_jobs` count is one below `max_offers` — i.e., nearly enough jobs but not yet at target.

**Contract**: Build a state fixture with `valid_jobs` list of length `max_offers - 1`, `scout_runs = 0`. Call `should_rescout(state)` directly. Assert return value is `"rescout"`.

#### 3. deduplicate_seen_jobs reducer

**File**: `tests/test_graph.py`

**Intent**: Prove the `deduplicate_seen_jobs` reducer strips duplicates when the same URL appears in both the `existing` and `new` lists — simulating two scout cycles that both found the same posting.

**Contract**: Import `deduplicate_seen_jobs` from `src.schema.state`. Call it with `existing=["https://a.com", "https://b.com"]`, `new=["https://b.com", "https://c.com"]`. Assert the returned list has length 3 and contains all three unique URLs. Call it again with two fully overlapping lists; assert length equals the number of unique URLs.

### Success Criteria

#### Automated Verification

- All existing + new tests in `test_graph.py` pass: `uv run pytest tests/test_graph.py -v`
- Black formatting: `uv run black tests/test_graph.py --check`

#### Manual Verification

- New boundary tests are named clearly enough that a failure message identifies which boundary broke.

**Implementation Note**: Pause after Phase 2 for manual confirmation before proceeding.

---

## Phase 3: Risk #6 — RAG Relevance Integration Test

### Overview

Create `tests/integration/test_rag_retrieval.py`. Insert two `CVEmbedding` rows with orthogonal deterministic vectors into the real test DB. Query with a vector identical to the software chunk's vector using `limit=1`. Assert the returned chunk is the domain-relevant one.

### Changes Required

#### 1. New integration test file

**File**: `tests/integration/test_rag_retrieval.py` (new)

**Intent**: Prove that `CVEmbeddingRepository.search_by_user_and_query` returns the semantically relevant CV chunk over an irrelevant decoy — using pgvector's actual cosine-distance ranking, not a mock. This closes the "asserting only non-empty" anti-pattern.

**Contract**:

Use `real_session` and `user_a` fixtures from `tests/integration/conftest.py` (import pattern identical to `test_user_isolation.py`).

Insert two `CVEmbedding` objects via `CVEmbeddingRepository.bulk_insert`:
- Software chunk: `chunk_text="Senior Python software engineer with 5 years of backend experience"`, `embedding=[1.0] + [0.0] * 1535`
- Cooking chunk: `chunk_text="Expert pastry chef specializing in French cuisine and dessert"`, `embedding=[0.0, 1.0] + [0.0] * 1534`

Call `CVEmbeddingRepository.search_by_user_and_query(real_session, user_a.id, query_embedding, limit=1)` where `query_embedding = [1.0] + [0.0] * 1535` (identical to the software chunk vector → cosine distance = 0.0).

Assert:
- Returned list has length 1.
- `result[0].chunk_text` contains `"software"` (or matches the software chunk text exactly).
- `result[0].chunk_text` does NOT contain `"pastry"`.

The test must call `await real_session.flush()` after bulk insert so rows are visible within the same SAVEPOINT transaction before the query runs.

### Success Criteria

#### Automated Verification

- New integration test passes: `uv run pytest tests/integration/test_rag_retrieval.py -v`
- Full integration suite still passes: `uv run pytest tests/integration/ -v`
- Black formatting: `uv run black tests/integration/test_rag_retrieval.py --check`

#### Manual Verification

- Test failure message on a wrong result names the actual `chunk_text` returned — verify this by temporarily swapping the vectors and confirming the failure is readable.

**Implementation Note**: Pause after Phase 3 for manual confirmation before archiving this change.

---

## Testing Strategy

### Unit Tests

- Risk #4: parametrize over 5 expiration phrases; mock HTTP + LLM per parametrized case.
- Risk #4: retry exhaustion — mock LLM to always raise; assert graceful invalid result.
- Risk #5: call `should_rescout` directly with state dictionaries; no graph invocation needed.
- Risk #5: call `deduplicate_seen_jobs` directly; pure function, no fixtures.

### Integration Tests

- Risk #6: real PostgreSQL with pgvector extension (from Phase 1 conftest); SAVEPOINT isolation; no network calls; no Vision LLM.

### Manual Testing Steps

1. After Phase 1: run `uv run pytest tests/test_validator_async.py -v` and verify each parametrized phrase appears as a named test case in the output.
2. After Phase 2: run `uv run pytest tests/test_graph.py -v` and verify boundary test names are descriptive.
3. After Phase 3: temporarily swap the software/cooking embedding vectors in the test, run it, and confirm the failure message names the wrong `chunk_text` — then revert.

## References

- Test plan: `context/foundation/test-plan.md` §2 Risks #4, #5, #6
- Phase 1 fixture pattern: `tests/integration/conftest.py`
- Phase 1 test pattern: `tests/integration/test_evaluation_persistence.py`
- Reducer under test: `src/schema/state.py:31-33`
- Repository under test: `src/db/repositories.py:94-113`
- Validator under test: `src/tools/job_validator.py:34-146`, `157-189`
- Conditional edge under test: `src/graph.py:10-46`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles. See `references/progress-format.md`.

### Phase 1: Risk #4 — Validator False-Negative Tests

#### Automated

- [x] 1.1 All existing + new tests in test_validator_async.py pass: `uv run pytest tests/test_validator_async.py -v`
- [x] 1.2 Black formatting: `uv run black tests/test_validator_async.py --check`

#### Manual

- [x] 1.3 Each parametrized phrase case listed individually in pytest output

### Phase 2: Risk #5 — Rescout Boundary Tests

#### Automated

- [x] 2.1 All existing + new tests in test_graph.py pass: `uv run pytest tests/test_graph.py -v`
- [x] 2.2 Black formatting: `uv run black tests/test_graph.py --check`

#### Manual

- [x] 2.3 New boundary tests named clearly enough that failure message identifies which boundary broke

### Phase 3: Risk #6 — RAG Relevance Integration Test

#### Automated

- [x] 3.1 New integration test passes: `uv run pytest tests/integration/test_rag_retrieval.py -v`
- [x] 3.2 Full integration suite passes: `uv run pytest tests/integration/ -v`
- [x] 3.3 Black formatting: `uv run black tests/integration/test_rag_retrieval.py --check`

#### Manual

- [x] 3.4 Failure message on wrong result names the actual chunk_text returned (verified by temporarily swapping vectors)
