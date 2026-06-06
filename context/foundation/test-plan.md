# Test Plan

> Phased test rollout for this project. Strategy is frozen at the top
> (§1–§5); cookbook patterns at the bottom (§6) fill in as phases ship.
> Read before writing any new test.
>
> Refresh: re-run `/10x-test-plan --refresh` when stale (see §8).
>
> Last updated: 2026-06-07 (Phase 4 implemented)

---

## 1. Strategy

Tests follow three non-negotiable principles for this project:

1. **Cost × signal.** The cheapest test that gives a real signal for the
   risk wins. Do not promote to e2e because e2e "feels safer." Do not put a
   vision model on top of a deterministic check that already catches the
   regression.
2. **User concerns are first-class evidence.** Risks anchored in "the
   team is worried about X, and the failure would surface somewhere in
   \<area\>" carry the same weight as PRD lines or hot-spot data.
3. **Risks are scenarios, not code locations.** This plan documents *what
   could fail* and *why we believe it's likely* — drawn from documents,
   interview, and codebase *signal* (churn, structure, test base). It does
   NOT claim to know which line owns the failure. That knowledge is
   produced by `/10x-research` during each rollout phase. If the plan and
   research disagree about where the failure lives, research is the
   ground truth.

Hot-spot scope used for likelihood weighting: `src/`, `tests/`, `frontend/app/`,
`frontend/components/`, `frontend/lib/`, `frontend/hooks/` — 49 commits / 30 days.

---

## 2. Risk Map

The top failure scenarios this project must protect against, ordered by
risk = impact × likelihood. Risks are failure scenarios in user / business
terms, not test names. The Source column cites the *evidence that surfaced
this risk* — never a specific file as "where the failure lives" (that is
research's job, see §1 principle #3).

| # | Risk (failure scenario) | Impact | Likelihood | Source (evidence — not anchor) |
|---|---|---|---|---|
| 1 | Evaluation persistence write fails silently after workflow completes — API returns 200 with scores in JSON but job list shows nulls on reload | High | High | Roadmap "Parked → evaluation-persistence"; archive `2026-06-01-evaluation-persistence/plan.md`; hot-spot `src/db/` (23 changes/30d) |
| 2 | User data isolation missing — a JWT-authenticated request returns or modifies rows belonging to a different user_id | High | High | PRD §Access Control; interview Q4; hot-spot `src/api/routes/` (37 changes/30d) |
| 3 | Streaming workflow zombie — SSE disconnect leaves orphan `create_task` running; subsequent retry produces competing writes to the same evaluation rows | High | Medium | Interview Q1; roadmap S-06 streaming notes; hot-spot `src/api/routes/` (37 changes/30d) |
| 4 | Job validator false negative — expired/dead job passes HTTP + LLM check and reaches Orchestrator; evaluation generated for a non-existent posting | Medium | High | Interview Q2 (burned here); hot-spot `src/tools/` (28 changes/30d) |
| 5 | LangGraph rescout conditional edge error — `should_rescout` returns wrong branch; workflow loops forever, terminates early, or advances with zero valid jobs | Medium | Medium | Interview Q3; hot-spot `src/graph.py` (5 changes/30d); hot-spot `src/agents/` (30 changes/30d) |
| 6 | RAG context retrieval returns irrelevant CV chunks — Orchestrator scores jobs against wrong CV context; match scores confidently wrong | High | Medium | Interview Q3+Q4; hot-spot `src/tools/` (28 changes/30d), `src/tools/vectordb.py` specifically (11 changes/30d) |
| 7 | JWT or OpenRouter API key leaks into error response body or loguru log entry | High | Low | PRD §Auth Security ("no plaintext secrets in code"); hot-spot `src/config/` (12 changes/30d) |

### Risk Response Guidance

| Risk | What would prove protection | Must challenge | Context `/10x-research` must ground | Likely cheapest layer | Anti-pattern to avoid |
|---|---|---|---|---|---|
| #1 | After workflow completes, every shortlisted job has a non-null `match_score` in the DB that survives a page reload | "API returned 200 means persistence succeeded" | upsert call path; async exception handling after `graph.ainvoke()`; sync vs streaming path divergence | integration (real async DB session) | asserting only the API response JSON; not verifying the DB state |
| #2 | A request authenticated as user A cannot retrieve or modify user B's jobs, CVs, or evaluations | "JWT middleware being present means user_id isolation is enforced on every query" | which endpoints filter by user_id; which DB queries lack the filter; JWT extraction and user_id propagation shape | integration (two test users, cross-user request) | testing only happy-path single-user flows |
| #3 | On SSE client disconnect, the background task is cancelled and no orphan write occurs to the evaluations table | "The `asyncio.create_task` pattern is fire-and-forget safe" | how disconnect is detected in FastAPI/Starlette; whether task cancellation propagates through the graph to DB writes; whether the upsert constraint is sufficient to prevent duplicate rows from a retry | integration (disconnect simulation) | testing only successful stream completion |
| #4 | A job with a dead URL or expiration phrase in its body is classified as invalid and excluded from Orchestrator input | "HTTP 200 means the job is active" | the two-stage check logic (HTTP status + LLM expiration phrase detection); what phrases constitute a false negative; error handling when HTTP request itself fails | unit (mock HTTP responses + mock LLM for known expiration phrases) | testing only the 404/410 HTTP case; ignoring the LLM expiration-phrase path |
| #5 | Given N valid jobs < max_valid_offers and scout_runs < max_scout_runs, the graph rescouts; given max_scout_runs reached, it proceeds without looping | "Existing tests in test_graph.py cover the edge cases" | the exact boolean logic of `should_rescout`; which state fields it reads; seen_jobs deduplication reducer correctness | unit (state fixture + direct function call) | asserting only the happy path (enough jobs found on first scout) |
| #6 | Orchestrator receives CV context chunks that semantically match the job domain being scored | "Mocked vector store tests cover RAG quality" | the embedding model, similarity metric, chunk size, and query construction used in retrieval; what a "wrong chunk" looks like in practice | integration (real pgvector query against test embeddings) | asserting only that a non-empty list is returned |
| #7 | A 422 or 500 response body and loguru output contain no API keys, JWT tokens, or raw Python tracebacks | "FastAPI's default error handling is safe" | how errors are caught and serialized across all error handlers; what loguru captures at ERROR/WARNING level; whether Pydantic validation errors expose internal field values | unit (trigger validation errors; assert response body and log content) | testing only that the endpoint returns 4xx; not inspecting body or log content |

---

## 3. Phased Rollout

Each row is a discrete rollout phase that will open its own change folder
via `/10x-new`. Status moves left-to-right through the values below; the
orchestrator updates Status as artifacts appear on disk.

| # | Phase name | Goal (one line) | Risks covered | Test types | Status | Change folder |
|---|---|---|---|---|---|---|
| 1 | Data integrity | Prove evaluation writes survive to DB and user_id isolation holds under two-user requests | #1, #2 | integration (real async DB session, two-user fixture) | archived | context/archive/2026-06-01-testing-data-integrity/ |
| 2 | Agent logic regression | Catch validator false negatives, rescout edge errors, and RAG retrieval quality drift | #4, #5, #6 | unit + integration | archived | context/archive/2026-06-05-testing-agent-logic-regression/ |
| 3 | Streaming resilience | Prove orphan tasks cancel on SSE disconnect and competing writes are handled by the upsert | #3 | integration (disconnect simulation) | archived | context/archive/2026-06-05-testing-streaming-resilience/ |
| 4 | Security gate | Prove no secrets or tracebacks escape into error responses or logs | #7 | unit (response + log inspection) | archived | context/archive/2026-06-05-testing-security-gate/ |

---

## 4. Stack

| Layer | Tool | Version | Notes |
|---|---|---|---|
| unit + integration | pytest | ≥9.0.3 | Configured in `pyproject.toml` `[tool.pytest.ini_options]` |
| async test support | pytest-asyncio | ≥0.24.0 | Required for all async node and endpoint tests |
| mocking | pytest-mock + unittest.mock | ≥3.14.0 | AGENTS.md hard rule: no real network calls in tests |
| HTTP client in tests | httpx | ≥0.28.0 | Used with FastAPI `TestClient` / `AsyncClient` |
| DB (integration) | real async SQLAlchemy session against test PostgreSQL | — | Phase 1 will confirm fixture pattern; see §3 Phase 1 |
| e2e | none yet — see §3 Phase 3 | — | Streaming resilience tests use FastAPI async test client, not a browser |
| CI | none configured | — | Gates are local-only until CI is wired (future roadmap item) |

**Stack grounding tools (current session):**
- Docs: none — Context7 not available in this session; no framework docs MCP; checked: 2026-06-01
- Search: none — Exa.ai not available; no web search MCP; checked: 2026-06-01
- Runtime/browser: none — no Playwright MCP or browser tool; not used; checked: 2026-06-01
- Provider/platform: none — no GitHub, Supabase, or database MCP; checked: 2026-06-01

---

## 5. Quality Gates

| Gate | Where | Required? | Catches |
|---|---|---|---|
| lint + typecheck (black + mypy strict) | local | required now — AGENTS.md hard rule | type drift, missing annotations |
| unit + integration | local | required after §3 Phase 1 lands | logic regressions, DB isolation failures |
| rescout + validator unit tests | local | required after §3 Phase 2 lands | conditional edge regressions |
| streaming disconnect test | local | required after §3 Phase 3 lands | orphan-task and competing-write regressions |
| secret-leak response inspection | local | required after §3 Phase 4 lands | credential exposure in error paths |
| CI (GitHub Actions or equivalent) | CI on PR | planned — no phase assigned yet; required before any cloud deployment | all of the above, automatically |

---

## 6. Cookbook Patterns

How to add new tests in this project. Each sub-section fills in once the
relevant rollout phase ships; before that, the sub-section reads
"TBD — see §3 Phase \<N\>."

### 6.1 Adding a unit test

TBD — see §3 Phase 2 (agent logic regression patterns established there).

### 6.2 Adding an integration test against the DB

TBD — see §3 Phase 1 (two-user async DB fixture pattern established there).

### 6.3 Adding a test for a new API endpoint

TBD — see §3 Phase 1 (cross-user isolation pattern) and Phase 2 (agent
endpoint pattern).

### 6.4 Adding a streaming / SSE test

TBD — see §3 Phase 3 (disconnect simulation pattern established there).

### 6.5 Adding a security / response-inspection test

Pattern established in Phase 4 (`tests/unit/test_security_gate.py`).

**Key elements:**
- Use `app.dependency_overrides[get_current_user]` and `app.dependency_overrides[get_db]` to bypass auth/DB.
  Always clear overrides in a `finally` block.
- Patch `src.api.main.init_db` and `src.api.main.get_agent_factory` when using
  `AsyncClient + ASGITransport(app=app)` as a context manager (triggers the lifespan).
- For the sync endpoint: inject via `AsyncClient`; assert `FAKE_SECRET not in response.text`.
- For the streaming endpoint: call the route handler directly (same pattern as §6.4);
  collect `body_iterator` chunks; assert no chunk contains the fake string.
- For the global exception handler: call `global_exception_handler(mock_request, exc)` directly;
  inspect `json.loads(response.body)`.
- For startup-log inspection: add a `logger.add(lambda msg: ...)` sink before entering the
  lifespan context; remove it in a `finally` block; assert the password substring is absent.
- Use a recognisable fake key string (e.g. `"sk-or-v1-FAKE-SECRET"`) so the assertion is
  unambiguous and the deliberate-regression check is easy to perform manually.

### 6.6 Per-rollout-phase notes

**Phase 4 — Security gate (2026-06-07)**

- Three `str(e)` response-body leaks were all in `workflows.py`; no other route files
  required changes.
- Migrating `AppConfig` fields to `SecretStr` required fixing the field default:
  wrapping the plain-string default in `SecretStr(...)` satisfies mypy strict mode
  (pydantic-settings coerces at runtime, but mypy sees the `Field(str)` type, not the
  coercion).
- Existing tests that called `pyjwt.encode/decode` with `config.jwt_secret_key` directly
  needed `.get_secret_value()` added — a mechanical find-and-replace across two test files.
- The `test_utils.py` mock fixture for `openrouter_api_key` needed to return `SecretStr("mock-key")`
  instead of a plain string so `.get_secret_value()` is available on the mock value.
- Deliberate-regression check for the streaming test: use an `async def` with `raise` before
  `yield` — Python still treats it as an async generator (the `yield` is unreachable but present),
  and the first `__anext__()` call raises the exception into the `except Exception` block in
  `run_graph()`, which then puts the sanitised error event into the SSE queue.

---

## 7. What We Deliberately Don't Test

Exclusions agreed during the rollout (Phase 2 interview, Q5). Future
contributors should respect these unless the underlying assumption changes.

- **Streamlit UI (`ui.py`)** — deprecated and replaced by Next.js frontend. Re-evaluate if Streamlit is restored. (Source: interview Q5.)
- **OrioSearch internal job-ranking logic** — external service, not our code. Re-evaluate if we own the service or implement a fallback. (Source: interview Q5.)
- **Next.js snapshot and UI tests** — frontend is thin and changes fast; snapshot churn produces false failures with no signal. Re-evaluate if frontend grows a stable component library. (Source: interview Q5.)
- **Untrusted input / LLM prompt injection via `initial_prompt`** — local-only deployment, single-user, self-inflicted blast radius. Re-evaluate if the system is exposed to the public internet. (Source: abuse lens review; PRD §Non-Goals "No cloud hosting".)
- **Resource abuse / rate-limit bypass** — no rate limiting planned for local deployment; user burns their own API credits. Re-evaluate if multi-tenant cloud deployment is added. (Source: PRD §Non-Goals.)

---

## 8. Freshness Ledger

- Strategy (§1–§5) last reviewed: 2026-06-01
- Stack versions last verified: 2026-06-01
- AI-native tool references last verified: 2026-06-01 (none in use)

Refresh (`/10x-test-plan --refresh`) when:

- a new top-3 risk surfaces from the roadmap or archive,
- a recommended tool's `checked:` date is older than three months,
- the project's tech stack changes (new framework, new test runner),
- §7 negative-space no longer matches what the team believes.
