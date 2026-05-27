---
project: AgenticHire AI — Production Readiness Refactor
version: 1
status: draft
created: 2026-05-25
updated: 2026-05-27
architectural_note: "Graph-Workflow-API (S-06) implements unified orchestration endpoint, replacing initial plan for separate Orchestrator and Tailor endpoints. LangGraph is now the primary API entry point for job search workflows."
prd_version: 1
main_goal: speed
top_blocker: decisions
---

# Roadmap: AgenticHire AI — Production Readiness Refactor

> Derived from `context/foundation/prd.md` (v1) + auto-researched codebase baseline.
> Edit-in-place; archive when superseded.
> Slices below are listed in dependency order. The "At a glance" table is the index.

## Vision recap

AgenticHire AI is migrating from a local Streamlit + ChromaDB demo into a secure, multi-tenant, production-ready agent system. The binding problem is clear: multi-user state isolation and persistent infrastructure are foundational — adding features without them is technically unsustainable. This roadmap delivers Phase 1 (infrastructure + auth + agents ported) in speed mode: critical-path slices first (auth → API → pgvector), defer polish (Docker hardening, observability) to Phase 2.

## North star

**S-01: User can sign up and authenticate via FastAPI** — Smallest proof that the new API + auth infrastructure plumbing works. Ships early (after FastAPI and auth scaffolds), unlocks all downstream slices, validates the core hypothesis: multi-user architecture with persistent state.

> The north star — the smallest end-to-end slice that, if shipped first, proves the core hypothesis (here: multi-user infrastructure with persistent state) — is the one validation milestone a team needs to ship before adding complexity.

## At a glance

| ID    | Change ID                  | Outcome (user can …)                              | Prerequisites        | PRD refs       | Status    |
| ----- | -------------------------- | ------------------------------------------------- | -------------------- | -------------- | --------- |
| F-01  | `fastapi-scaffold`         | (foundation) FastAPI server running locally       | —                    | FR-004, FR-005, FR-006 | done  |
| F-02  | `postgresql-pgvector-setup` | (foundation) PostgreSQL + pgvector schema ready   | —                    | FR-009, FR-003, FR-007, FR-008 | done  |
| F-03  | `jwt-auth-middleware`      | (foundation) JWT tokens issued, auth endpoints live | F-01                | FR-001, FR-002 | done  |
| F-04  | `cv-vision-to-pgvector`    | (foundation) CV embeddings stored in pgvector    | F-02                | FR-009, FR-013 | done  |
| S-01  | `user-signup-auth`         | sign up with email + password and receive JWT    | F-01, F-02, F-03     | FR-001, FR-002, FR-003 | done  |
| S-02  | `user-login-refresh`       | log in and refresh JWT token                     | F-03, S-01           | FR-002         | done  |
| S-03  | `user-cv-upload`           | upload CV, trigger embedding, verify storage     | F-01, F-02, F-04     | FR-003, FR-009, FR-013 | done  |
| S-04  | `scout-api-endpoint`       | invoke job search via FastAPI endpoint           | F-01                 | FR-004, FR-011 | done      |
| S-05  | `validate-jobs-endpoint`   | invoke job validation via FastAPI endpoint       | F-01                 | FR-006         | done      |
| S-06  | `graph-workflow-api`        | unified workflow endpoint: Scout → Validate → Orchestrate → Tailor via LangGraph | F-01, F-04, S-05   | FR-005, FR-012, FR-014 | done  |
| S-07  | `tailor-api-endpoint`      | ~~invoke evaluation generation via FastAPI~~ (subsumed by S-06 unified workflow) | F-01, F-04           | FR-014         | subsumed  |
| S-08  | `user-job-list`            | retrieve personal job list (user-filtered)       | F-01, F-02           | FR-007         | proposed  |
| S-09  | `user-evaluations`         | retrieve personal evaluation scores               | F-01, F-02           | FR-008         | proposed  |
| F-05  | `docker-compose-hardening` | (foundation) full-stack Docker with health checks | F-01, F-02, F-03, F-04 | FR-010         | blocked   |

## Streams

Navigation aid — groups items into major feature threads. Each item appears in exactly one stream; streams share a common dependency on F-01 (FastAPI scaffold).

| Stream | Theme                          | Chain                                                  | Note                                                      |
| ------ | ------------------------------ | ------------------------------------------------------ | --------------------------------------------------------- |
| A      | Job discovery & validation     | F-01 → S-04 → S-05                                     | Scout and validate endpoints; feed results into scoring. |
| B      | Results dashboard              | F-02 → S-08 → S-09                                     | User views discovered jobs and evaluation scores.        |
| C      | User auth & session            | F-03 → S-01 → S-02                                     | User signup, login, token refresh; unlocks all workflows. |
| D      | CV-based semantic matching     | F-04 → S-03 → S-06 → S-07                              | Upload CV, retrieve context, score jobs, generate summaries. |

## Baseline

What's already in place in the codebase as of 2026-05-25 (auto-researched + confirmed).
Foundations below assume these are present and do NOT re-scaffold them.

- **Frontend:** Partial — Streamlit UI present (`ui.py`, v1.56.0); no React/Next.js infrastructure yet.
- **Backend / API:** Present (LangGraph) — Python CLI via `main.py`, LangGraph state machine (Scout, Orchestrator, Tailor agents). No FastAPI HTTP routes; runs synchronously via CLI or Streamlit.
- **Data:** Present (ChromaDB) — Vector store at `src/tools/vectordb.py` (CVVectorManager); ChromaDB persisted to `/data/chroma_db`. No PostgreSQL/pgvector yet.
- **Auth:** **Absent** — No auth provider, JWT, sessions, or middleware. System is completely anonymous.
- **Deploy / Infra:** Present — Multi-stage Dockerfile (Python 3.13), Docker Compose with Streamlit service, health checks. No CI/CD workflows.
- **Observability:** Partial — Loguru logging configured; LangFuse credentials in `.env` but tracing not active. No Sentry/Datadog/OTEL.

## Foundations

### F-01: FastAPI server scaffold

- **Outcome:** (foundation) FastAPI server running locally with basic project structure, route handlers, and dependency injection ready for agent endpoints.
- **Change ID:** `fastapi-scaffold`
- **PRD refs:** FR-004, FR-005, FR-006 (agent endpoints); FR-010 (Docker setup)
- **Unlocks:** S-01, S-02, S-03, S-04, S-05, S-06, S-07, S-08 (all API slices depend on server)
- **Prerequisites:** —
- **Parallel with:** F-02
- **Blockers:** —
- **Unknowns:** —
- **Risk:** FastAPI is new to the codebase (current system uses LangGraph + Streamlit/CLI). Risk: learning curve on async patterns, middleware setup. Mitigation: FastAPI is a standard industry library with extensive docs; Python LangGraph bindings exist.
- **Status:** done

### F-02: PostgreSQL + pgvector setup

- **Outcome:** (foundation) PostgreSQL container running locally with pgvector extension installed, schema created for users, jobs, CV embeddings, evaluation results.
- **Change ID:** `postgresql-pgvector-setup`
- **PRD refs:** FR-003 (user isolation), FR-007 (job list), FR-008 (evaluation scores), FR-009 (pgvector embeddings)
- **Unlocks:** S-01, S-03, S-05, S-06, S-07, S-08 (data-persistence and RAG-context slices)
- **Prerequisites:** —
- **Parallel with:** F-01
- **Blockers:** —
- **Unknowns:**
  - **CV file storage method** (filesystem with metadata vs Postgres bytea?) — Owner: user. Block: yes. Affects schema design and chunking strategy.
- **Risk:** pgvector + PostgreSQL are new layers (current system uses ChromaDB only). Risk: schema evolution, data migration testing. Mitigation: single-user local deployment simplifies schema (no sharding needed).
- **Status:** done

### F-03: JWT auth middleware

- **Outcome:** (foundation) JWT token generation, password hashing (bcrypt), auth middleware attached to FastAPI routes. All endpoints except `/signup` and `/login` require valid JWT.
- **Change ID:** `jwt-auth-middleware`
- **PRD refs:** FR-001 (signup), FR-002 (login), Access Control Changes section
- **Unlocks:** S-01, S-02 (authenticated endpoints), and implicitly S-03–S-08 (all require user context from JWT)
- **Prerequisites:** F-01 (FastAPI server)
- **Parallel with:** F-04
- **Blockers:** —
- **Unknowns:**
  - **JWT token expiration window** (7 days vs 24 hours vs 1 hour?) — Owner: user. Block: yes. Affects session lifecycle and refresh token strategy.
- **Risk:** Implementing auth correctly is critical for security. Risk: token expiration edge cases, password validation bypass. Mitigation: use industry-standard libraries (PyJWT, passlib); strict code review on auth endpoints.
- **Status:** done

### F-04: CV Vision pipeline refactor

- **Outcome:** (foundation) CV ingestion refactored from ChromaDB to pgvector. PDF → images → Vision LLM OCR → embeddings → pgvector inserts. Embedding quality verified against sample CV regression test.
- **Change ID:** `cv-vision-to-pgvector`
- **PRD refs:** FR-009 (pgvector storage), FR-013 (Vision quality fidelity)
- **Unlocks:** S-03 (CV upload slice), S-05 (Orchestrator can retrieve CV context), S-06 (Tailor can retrieve CV context)
- **Prerequisites:** F-02 (pgvector schema must exist)
- **Parallel with:** F-03
- **Blockers:** —
- **Unknowns:**
  - **CV file storage method** (filesystem vs bytea) — Owner: user. Block: yes. Determines whether S-03 stores file path (FS) or binary (Postgres).
- **Risk:** Vision LLM + embeddings are performance-sensitive and must match prior ChromaDB quality. Risk: slow ingestion, embedding drift. Mitigation: regression test on sample CVs before/after refactor; caching strategy (hash-based caching from prior system retained).
- **Status:** done

### F-05: Docker Compose hardening

- **Outcome:** (foundation) Full-stack Docker Compose with all services (FastAPI, PostgreSQL, ChromaDB deprecation), health checks, resource limits, logging setup. Developers can run `docker-compose up` and have a production-like local environment.
- **Change ID:** `docker-compose-hardening`
- **PRD refs:** FR-010 (Docker Compose reproducibility)
- **Unlocks:** Deployment readiness, Phase 2+ infrastructure stability
- **Prerequisites:** F-01, F-02, F-03, F-04 (all components must be stable before hardening)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Docker composition and multi-service orchestration adds complexity. Risk: volume persistence, inter-service communication, environment variable leaks. Mitigation: current Dockerfile is already multi-stage and robust; Docker Compose exists (Streamlit version); reuse patterns.
- **Status:** blocked (Deferred to Phase 2 in speed mode. Phase 1a minimal Docker Compose is implicit in F-01/F-02; Phase 1e hardening is post-launch polish.)

## Slices

### S-01: User can sign up and authenticate

- **Outcome:** User visits `http://localhost:3000`, enters email + password, receives JWT token. Token persists in browser session. User is now authenticated and can make subsequent API calls.
- **Change ID:** `user-signup-auth`
- **PRD refs:** FR-001, FR-002, FR-003, US-01
- **Prerequisites:** F-01 (API server), F-02 (user table in Postgres), F-03 (JWT + bcrypt infrastructure)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:**
  - **Token expiration window** — Owner: user. Block: yes. Needed before F-03 is testable.
  - **Frontend framework choice** (React vs Next.js vs minimal?) — Owner: user. Block: no. Can ship with minimal HTML form for MVP.
- **Risk:** Signup form validates email and password strength; backend persists hashed password and issues JWT. Risk: password validation bypass, token leakage. Mitigation: F-03's auth middleware enforces bcrypt cost ≥ 12, JWT includes expiration timestamp.
- **Status:** done

### S-02: User can log in and refresh JWT

- **Outcome:** User enters email + password on login endpoint, receives new JWT. User can also refresh their token before expiration using a refresh endpoint. Old token invalidated on logout.
- **Change ID:** `user-login-refresh`
- **PRD refs:** FR-002
- **Prerequisites:** F-03 (auth infrastructure), S-01 (signup must come first in user flow)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Session lifecycle management (token expiration, refresh, logout invalidation) is easy to get wrong. Risk: token reuse, expired token persistence. Mitigation: F-03 includes refresh-token strategy in design review.
- **Status:** done (included in S-01 implementation)

### S-03: User can upload CV and trigger embedding

- **Outcome:** User uploads a PDF file via `/upload_cv` endpoint. System parses PDF → images → Vision LLM → embeddings → stores in pgvector keyed by user_id. User sees processing status and completion confirmation.
- **Change ID:** `user-cv-upload`
- **PRD refs:** FR-003 (CV storage), FR-009 (pgvector embedding), FR-013 (Vision quality)
- **Prerequisites:** F-01 (API server), F-02 (pgvector schema), F-04 (Vision pipeline refactored)
- **Parallel with:** S-04 (job discovery endpoint can run in parallel; they don't depend on each other)
- **Blockers:** —
- **Unknowns:**
  - **CV file storage method** — Owner: user. Block: yes. Determines implementation (save to filesystem + store path, or save to Postgres bytea).
- **Risk:** Vision LLM + embedding quality must match prior system. PDF parsing edge cases (corrupted files, unusual fonts, scanned images). Risk: slow ingestion (Vision LLM is bottleneck). Mitigation: F-04 includes regression test; hash-based caching from prior system retained.
- **Status:** done

### S-04: Scout agent invokable via FastAPI

- **Outcome:** Endpoint `POST /search_jobs` bound to Scout agent. Agent accepts search criteria (target_criteria from config or user input), queries OrioSearch, scrapes job postings, returns raw job listings. Results are persisted to user's job table.
- **Change ID:** `scout-api-endpoint`
- **PRD refs:** FR-004 (Scout endpoint), FR-011 (OrioSearch integration preserved)
- **Prerequisites:** F-01 (API server)
- **Parallel with:** S-05, S-06, S-07, S-03 (all depend on F-01; can run in parallel once F-01 is ready)
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Agent logic is unchanged from prior system; risk is in API binding and state serialization. Risk: job duplication across rescout cycles. Mitigation: Prior system has rescout + seen_jobs deduplication logic (operator.add + custom reducer); port as-is.
- **Status:** done

### S-05: Validate jobs via FastAPI

- **Outcome:** Endpoint `POST /validate_jobs` accepts raw job listings, filters invalid jobs (dead links, expired postings), removes duplicates, enforces max_valid_offers limit. Returns validated job list, rejected_jobs list, and validation status.
- **Change ID:** `validate-jobs-endpoint`
- **PRD refs:** FR-006 (Validate endpoint)
- **Prerequisites:** F-01 (API server)
- **Parallel with:** S-06, S-07, S-03 (can run in parallel with agent endpoints)
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Validation logic (HTTP checks, LLM expiration detection) is unchanged from prior system. Risk: false negatives (invalid links pass), false positives (valid links rejected). Mitigation: Preserve prior logic (HTTPValidator + ExpirationCheck utility); add regression tests.
- **Status:** done

### S-06: Unified workflow endpoint via LangGraph

- **Outcome:** Endpoint `POST /api/workflows/search-jobs` invokes LangGraph as master orchestrator. Accepts search criteria or pre-found jobs; executes Scout (optional) → Validate → Orchestrator (RAG-based scoring) → Tailor (evaluation) in one unified call. Returns all jobs with scores, shortlisted jobs with evaluations, rejected jobs with reasons. Orchestrator logs all decisions with [ORCHESTRATOR] prefix for transparency.
- **Change ID:** `graph-workflow-api`
- **PRD refs:** FR-005 (unified orchestration), FR-012 (OpenRouter scoring preserved), FR-014 (evaluation generation)
- **Prerequisites:** F-01 (API server), F-04 (CV context in pgvector for RAG), S-05 (validation logic available)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Unified endpoint coordinates multiple agents in sequence; risk: timeout on long pipelines, partial failure handling. Mitigation: per-job error tracking; graceful degradation (missing CV, individual job failures don't block other jobs).
- **Status:** done (Implemented in change `graph-workflow-api` with Phases 1–3 complete: logging, endpoint, tests)
- **Implementation notes**: Replaces prior plan for separate `/api/score_jobs` and `/api/evaluate_job/{job_id}` endpoints. LangGraph becomes the primary API orchestrator, not just CLI/Streamlit. Endpoint handles state initialization, CV context retrieval, graph invocation with async/await, and comprehensive error handling with per-job tracking.

### S-07: Tailor agent invokable via FastAPI

- **Outcome:** ~~Endpoint `POST /evaluate_job/{job_id}` bound to Tailor agent~~ **SUBSUMED by S-06** — Tailor agent is now invoked as the final step of the unified `/api/workflows/search-jobs` workflow. Retrieves CV context + job description, generates single-sentence evaluation summary per shortlisted job (score ≥ 0.6). Evaluation included in the unified response.
- **Change ID:** `tailor-api-endpoint` (consolidated into `graph-workflow-api` S-06)
- **PRD refs:** FR-014 (reasoning unchanged, now part of unified workflow)
- **Prerequisites:** F-01 (API server), F-04 (CV context), S-06 (unified workflow)
- **Parallel with:** —
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Tailor agent reasoning unchanged; risk mitigated by unified workflow error handling.
- **Status:** subsumed (Tailor is now part of S-06 unified workflow. No separate endpoint needed; clients call `/api/workflows/search-jobs` once to get complete results including evaluations.)

### S-08: User can retrieve personal job list

- **Outcome:** Endpoint `GET /jobs` returns user's discovered jobs (paginated, sorted by date). Response includes job title, company, link, discovery date, match score (if scored). User sees only their own jobs.
- **Change ID:** `user-job-list`
- **PRD refs:** FR-007 (view job list)
- **Prerequisites:** F-01 (API server), F-02 (jobs table keyed by user_id)
- **Parallel with:** S-09
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Database query performance for large job lists. Risk: N+1 queries, slow pagination. Mitigation: indexed queries on user_id; limit default page size.
- **Status:** proposed (ready after F-02)

### S-09: User can retrieve personal evaluation scores

- **Outcome:** Endpoint `GET /evaluations` returns user's scored jobs (paginated). Response includes job title, company, match score, evaluation summary. User sees only their own evaluations.
- **Change ID:** `user-evaluations`
- **PRD refs:** FR-008 (view evaluation scores)
- **Prerequisites:** F-01 (API server), F-02 (evaluations table keyed by user_id)
- **Parallel with:** S-08
- **Blockers:** —
- **Unknowns:** —
- **Risk:** Same as S-08.
- **Status:** proposed (ready after F-02)

## Backlog Handoff

| Roadmap ID | Change ID                   | Suggested issue title                               | Ready for `/10x-plan` | Notes |
| ---------- | --------------------------- | --------------------------------------------------- | --------------------- | ----- |
| F-01       | `fastapi-scaffold`          | Set up FastAPI server with basic routing            | yes                   | No upstream dependencies; start here. |
| F-02       | `postgresql-pgvector-setup` | Initialize PostgreSQL + pgvector schema             | no                    | Blocked: Q2 (CV file storage) affects schema design. Resolve before planning. |
| F-03       | `jwt-auth-middleware`       | Implement JWT tokens and auth middleware            | no                    | Blocked: Q1 (token expiration window) affects design. Resolve before planning. |
| F-04       | `cv-vision-to-pgvector`     | Migrate CV embeddings from ChromaDB to pgvector     | no                    | Blocked: Q2 (CV file storage) affects implementation. Resolve before planning. |
| S-01       | `user-signup-auth`          | User signup and JWT authentication (north star)    | no                    | North star slice; ready after F-01, F-02, F-03. Unblock by resolving Q1. |
| S-02       | `user-login-refresh`        | User login and token refresh                        | no                    | Depends on S-01 and F-03. Plan after S-01 is ready. |
| S-03       | `user-cv-upload`            | CV file upload and pgvector embedding              | no                    | Blocked: Q2 (CV storage). Unblock by resolving Q2. Parallel with S-04. |
| S-04       | `scout-api-endpoint`        | Scout agent as FastAPI endpoint                    | yes                   | Minimal dependencies; can start after F-01. Parallel with S-05, S-06, S-08. |
| S-05       | `validate-jobs-endpoint`    | Validate endpoint filters invalid/expired jobs      | yes                   | Minimal dependencies; can start after F-01. Feeds S-06. |
| S-06       | `orchestrator-api-endpoint` | Orchestrator agent as FastAPI endpoint with RAG    | no                    | Depends on F-04 (CV context) and S-05 (validated jobs). Unblock by resolving F-04. |
| S-07       | `tailor-api-endpoint`       | Tailor agent as FastAPI endpoint                   | no                    | Depends on S-06 (shortlisted jobs). Unblock by completing S-06. |
| S-08       | `user-job-list`             | User job list retrieval endpoint                   | yes                   | Depends on F-02. Parallel with S-09. |
| S-09       | `user-evaluations`          | User evaluation scores retrieval endpoint          | yes                   | Depends on F-02. Parallel with S-08. |
| F-05       | `docker-compose-hardening`  | Harden Docker Compose with health checks & limits  | no                    | Blocked: Deferred to Phase 2 in speed mode. Not critical for MVP. |

## Open Roadmap Questions

1. **Q1: JWT token expiration window** — How long should tokens live? Options: 7 days (long-lived, convenient for local dev), 24 hours (tighter security), 1 hour (production standard). Owner: user (design decision). Block: **yes** — F-03 design and refresh-token strategy depend on this.

2. **Q2: CV file storage method** — Should CV files be stored on the filesystem (faster, simpler backups) or as bytea blobs in Postgres (simpler for containerized deployment)? Owner: user (design decision). Block: **yes** — F-02 schema and F-04 implementation both depend on this choice.

3. **Q3: Frontend framework choice** — React vs Next.js vs Vue vs minimal HTML? (Deferred; Phase 1 can ship with minimal forms; full UI is Phase 2.) Owner: user. Block: no.

4. **Q4: Latency & uptime targets** — Is sub-2-second end-to-end acceptable? 99.9% uptime required? (Local-only deployment, low SLA needed.) Owner: user. Block: no.

5. **Q5: Resume Tweak Agent output format (Phase 3)** — Markdown diff, bulleted list, narrative? (Phase 3 work, not Phase 1.) Owner: user. Block: no.

## Parked

- **Phase 2 (Human-in-the-Loop approval workflow)** — Why parked: Deferred pending Phase 1 completion. PRD §Success Criteria §Secondary.
- **Phase 3 (Resume Tweak Agent)** — Why parked: Feature extension, not MVP infrastructure. PRD §Non-Goals.
- **Cloud hosting, Kubernetes, serverless infrastructure** — Why parked: Local Docker Compose only for Phase 1. PRD §Non-Goals.
- **Enterprise RBAC, team spaces, multi-organization support** — Why parked: Individual workspace model only. PRD §Non-Goals.
- **API rate-limiting, usage monitoring, analytics, telemetry** — Why parked: Local deployment, no scale concerns. PRD §Non-Goals.
- **Docker Compose hardening (Phase 1e polish)** — Why parked: Speed goal defers this to Phase 2; Phase 1a minimal Docker Compose is sufficient for MVP. PRD §Phase 1 Sub-Phases.

## Done

- **F-01: (foundation) FastAPI server running locally** — Archived 2026-05-25 → `context/archive/2026-05-25-fastapi-scaffold/`. Lesson: —.
- **F-02: (foundation) PostgreSQL + pgvector schema ready** — Archived 2026-05-25 → `context/archive/2026-05-25-postgresql-pgvector-setup/`. Lesson: —.
- **F-03: (foundation) JWT tokens issued, auth endpoints live** — Archived 2026-05-25 → `context/archive/2026-05-25-jwt-auth-middleware/`. Lesson: —.
- **F-04: (foundation) CV embeddings stored in pgvector** — Archived 2026-05-25 → `context/archive/2026-05-25-cv-vision-to-pgvector/`. Lesson: —.
- **S-01: sign up with email + password and receive JWT** — Archived 2026-05-25 → `context/archive/2026-05-25-user-signup-auth/`. Lesson: —.
- **S-02: log in and refresh JWT token** — Completed 2026-05-25 (included in S-01). Lesson: —.
- **S-03: upload CV, trigger embedding, verify storage** — Archived 2026-05-25 → `context/archive/2026-05-25-user-cv-upload/`. Lesson: —.
- **S-04: invoke job search via FastAPI endpoint** — Archived 2026-05-25 → `context/archive/2026-05-25-scout-api-endpoint/`. Lesson: —.
- **S-05: invoke job validation via FastAPI endpoint** — Archived 2026-05-26 → `context/archive/2026-05-26-validate-jobs-endpoint/`. Lesson: —.
- **S-06: unified workflow endpoint via LangGraph** — Implemented 2026-05-27 in change `graph-workflow-api` (supersedes earlier `orchestrator-api-endpoint` plan). Endpoint `/api/workflows/search-jobs` unifies Scout → Validate → Orchestrate → Tailor pipeline with [ORCHESTRATOR] logging and per-job error handling. S-07 (tailor) now subsumed. Lesson: LangGraph as primary API orchestrator proves superior to separate agent endpoints; consolidation reduces API surface and simplifies client integration.
