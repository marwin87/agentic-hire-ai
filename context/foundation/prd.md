---
project: AgenticHire AI — Production Readiness Refactor
version: 1
status: draft
created: 2026-05-19
context_type: brownfield
product_type: web-app
target_scale:
  users: small (individual developers)
  latency: # TODO: perceived response time target — see Open Questions
  uptime: # TODO: availability requirement — see Open Questions
timeline_budget:
  delivery_weeks: 4
  after_hours_only: true
---

# AgenticHire AI — Production Readiness Refactor

## Current System Overview

AgenticHire AI is a multi-agent job application system built on LangGraph. The current system is:

- **Execution model**: Single-threaded Streamlit UI or CLI invocation (main.py)
- **Vector storage**: ChromaDB local instance
- **User model**: Anonymous, one-user-at-a-time workflow (no multi-tenancy, no session persistence)
- **External integrations**: OrioSearch (job discovery), OpenRouter (LLM reasoning), Vision LLM (CV parsing)
- **Agent workflow**: Autonomous end-to-end execution (Scout → Validate → Orchestrate → Tailor)

The system successfully handles job search, CV matching via RAG, and job evaluation. Agent logic is production-grade; infrastructure is fragile — no multi-tenancy, no persistent state across sessions, no access control.

---

## Problem Statement & Motivation

**The binding problem**: Scale AgenticHire AI from a local developer demo into a secure, production-ready, multi-tenant agent application.

The refactoring is not independent features; the enhancements form a strict dependency chain:

- Human-in-the-Loop (HITL) dashboard for paused workflows requires an asynchronous backend to handle state interruption.
- Asynchronous backend state persistence requires a relational database (not ChromaDB).
- Multi-user state storage requires access control to prevent data leaks.
- High-value compute agents (Resume Tweak) require auth to prevent unauthorized API token exploitation.

**Why now**: The current architecture blocks scaling beyond a demo. A production system requires multi-tenant isolation, persistent state, and secure access control. These are foundational — adding features without them is technically unsustainable.

---

## User & Persona

**Primary persona**: Individual software engineers and AI developers managing their own high-end job search.

The persona remains laser-focused on solo users. This is NOT a tool for HR teams, recruitment agencies, or multi-user organizations.

**Access model**: Email/Password signup → JWT-secured workspace. No multi-tenant enterprise features (teams, RBAC, SSO, organization spaces) — individual accounts only, optimized for local Docker Compose execution on developer machines.

**Why this scoping matters**: The target audience runs this locally, so authentication is straightforward (local JWT + bcrypt). No cloud scale concerns (load balancers, Kubernetes, serverless), zero infrastructure costs (users provide API keys, run compute locally). The codebase is architecturally ready for future cloud migration, but that is not required.

---

## Success Criteria

### Primary
Phase 1 (infrastructure + auth + agents ported) complete and working end-to-end within 4 weeks.

- FastAPI backend serving LangGraph agents asynchronously
- PostgreSQL storing user data, job results, CV embeddings
- JWT auth protecting user isolation (user_id enforced at DB and API layers)
- Docker Compose runs full stack locally with one command
- Agents produce same-quality results as prior system, now multi-user

### Secondary
Phase 2 (HITL) partially implemented or started (if time permits after Phase 1).

### Guardrails
- No regressions in core agent logic, prompts, or scoring algorithms
- No data loss; CV upload and embeddings match prior system's quality
- Test coverage must verify agent logic remains unchanged (regression tests on sample CVs)

---

## User Stories

### US-01: Developer uploads CV and authenticates

```
Given: A developer has Docker Compose running locally
When: They visit http://localhost:3000 and sign up with email + password
Then: They are logged in with a JWT token, and can upload their CV PDF
And: The system parses the CV, generates embeddings, and stores them in pgvector
```

**Acceptance criteria:**
- Signup form validates email format and password strength
- Login persists JWT in session
- CV upload accepts PDF, shows processing status, completes within 30 seconds
- Embeddings match quality of prior ChromaDB version (verified via regression test on sample CVs)
- User can log out and return later; their data is persisted and isolated from other users

---

## Scope of Change

### New Capabilities
- **FR-001**: User can sign up with email + password
- **FR-002**: User can log in with JWT token
- **FR-003**: User can upload and store CV (isolated by user_id)
- **FR-007**: User can view personal job list (database-backed)
- **FR-010**: Full stack runs in Docker Compose locally

### Modified Capabilities
- **FR-004**: Scout Agent can be invoked via FastAPI endpoint (was: CLI-only or embedded in Streamlit)
- **FR-005**: Unified orchestration workflow via FastAPI (was: separate endpoints per agent). Single `/api/workflows/search-jobs` endpoint coordinates full pipeline: Scout (optional, if criteria provided) → Validate → Orchestrator (RAG-based scoring) → Tailor (evaluation) in one request.
- **FR-006**: Validate can be invoked via FastAPI (now part of unified endpoint, was: CLI-only)
- **FR-009**: CV embeddings stored in pgvector (was: ChromaDB local instance)

### Preserved Capabilities
- **FR-011**: Scout discovers jobs via OrioSearch API (logic unchanged, same connector, same job payload)
- **FR-012**: Orchestrator scores jobs via OpenRouter (prompts unchanged, same reasoning, now via unified `/api/workflows/search-jobs`)
- **FR-013**: Vision pipeline parses CV with same quality (PDF → Images → Vision LLM, same embeddings quality)
- **FR-014**: Tailor generates evaluation text (reasoning unchanged, now persisted in database, part of unified workflow)

### Removed / Deprecated
- CLI (main.py) — fully replaced by FastAPI endpoints
- Streamlit UI (ui.py) — fully replaced by React/Next.js frontend
- ChromaDB — fully replaced by PostgreSQL + pgvector

---

## Constraints & Compatibility

### Backward Compatibility & Migration
**Data migration**: Fresh start. No data import from old system required. The old Streamlit UI and CLI are deprecated entirely; users of the current system will start fresh in the new web interface.

### Preserved Integrations
- Scout agent connection to OrioSearch API (same payload, new destination: Postgres)
- OpenRouter LLM gateway (same models, same prompts, unchanged reasoning)
- Vision LLM CV parsing logic (same PDF handling, same embeddings quality)
- Tailor agent evaluation reasoning (same prompts, now database-backed)

### Data Schema & Persistence
- All user-created data (CVs, job results, evaluation scores) is keyed by user_id
- CVs are persisted and associated with their owner
- Job results and embeddings are stored persistently, per-user
- Session state is persisted (preparation for Phase 2 HITL checkpointing)
- One user cannot see another user's data — enforced at database schema (user_id foreign keys) and API layer (JWT validation)

### Quality & Security Constraints
- **Auth Security**: Passwords must be hashed securely (bcrypt cost factor ≥ 12); JWT tokens include expiration; no plaintext secrets in code
- **Embedding Quality**: CV embeddings must produce same semantic search results as prior ChromaDB version (verified via regression test suite)
- **Agent Logic Fidelity**: Scout, Orchestrator, Tailor outputs must remain identical to prior system (no prompt changes, no scoring algorithm changes)
- **Local Performance**: End-to-end workflow (upload CV, search jobs, score) must complete in <2 minutes on developer machine (modern laptop, 8GB RAM)

### Operational Constraints
- Deployment target: Local Docker Compose only (no cloud hosting in scope)
- No horizontal scaling required (single-machine deployment)
- Zero infrastructure costs (users provide their own API keys and compute)

---

## Business Logic Changes

**Domain rule (preserved)**: Multi-user job matching using RAG-based semantic similarity between CV and job descriptions.

The binding problem introduced exactly one new domain rule: **user data isolation**. Every job search, CV embedding, and match score is tagged with `user_id` in the database. One user cannot see another user's data.

The scoring algorithm (0.0–1.0 relevance) and agent reasoning remain unchanged. No new decision logic is being introduced in Phase 1. Phase 2 (HITL) will add an approval workflow; Phase 3 (Resume Tweak) will add a new agent. Both are future phases.

---

## Access Control Changes

### Current State
Anonymous, one user per invocation. No user accounts, no sessions, no data isolation between runs.

### Planned Changes
- **Signup**: Email + password (validation rules: email format, password strength ≥ 12 chars with mixed case/numbers)
- **Hashing**: bcrypt (cost factor ≥ 12)
- **Session management**: JWT tokens issued on login, stored in browser session/localStorage
- **Token expiration**: # TODO: define expiration window (e.g., 7 days, 24 hours) — see Open Questions
- **API authentication**: All endpoints (except `/signup`, `/login`) require valid JWT in Authorization header
- **Data isolation**: All database queries filtered by user_id from the JWT payload

### No new roles
Individual workspace model only. No admin roles, no shared access, no organization tiers for MVP.

---

## Non-Goals (Explicitly NOT in Phase 1)

- No enterprise RBAC, team spaces, or multi-organization support
- No cloud hosting, Kubernetes, or serverless infrastructure
- No API rate-limiting or usage monitoring (local-only deployment)
- No analytics, telemetry, or observability
- Phase 2 (Human-in-the-Loop approval workflow) — optional, not MVP
- Phase 3 (Resume Tweak Agent) — optional, not MVP
- No migration tool for existing ChromaDB data
- No reverse-compatibility with CLI or Streamlit UI

---

## Open Questions

1. **Token expiration window** — How long should JWT tokens live? Options: 7 days (long-lived for local convenience) vs 24 hours (tighter security) vs 1 hour (production standard)? See Access Control Changes section.

2. **CV file storage** — Should CV files be stored on the filesystem (with Postgres storing metadata + path) or as bytea blobs in Postgres itself? Tradeoff: filesystem is faster; Postgres is simpler for containerized deployment.

3. **Frontend framework** — React vs Next.js vs Vue vs other? This will be selected in the `/10x-tech-stack-selector` phase, but flagging here for awareness.

4. **Latency & uptime targets** — No explicit targets provided. Is sub-2-second end-to-end acceptable? Is 99.9% uptime required locally?

5. **Phase 1 timeline realism** — User stated 4 weeks (after-hours/weekends, solo developer). This is ambitious for 5 sub-phases. May need scope recuts if mid-project bottlenecks emerge.

6. **Monitoring & alerting post-launch** — Beyond the 4-week Phase 1 MVP, how will the deployed system be monitored? Logging strategy, error tracking, performance dashboards?

7. **Resume Tweak Agent output format (Phase 3)** — Markdown diff, bulleted list, or narrative? Deferred to Phase 3 scoping.

---

## Phase 1 Sub-Phases (Delivery Plan)

Each sub-phase is testable and delivers working infrastructure. All are mandatory to ship within 4 weeks.

- **Phase 1a** (4-5 days): Backend scaffold — FastAPI server structure, PostgreSQL container, Docker Compose orchestration. Proves infrastructure works locally.
- **Phase 1b** (4-5 days): Auth layer — JWT tokens, bcrypt hashing, signup/login endpoints. Users can now create isolated accounts.
- **Phase 1c** (7-10 days): Agent porting — Scout, Validate, Orchestrator moved from CLI/Streamlit to FastAPI endpoints. Core workflow runs via API.
- **Phase 1d** (4-5 days): Vision + pgvector — CV ingestion pipeline refactored to pgvector inserts instead of ChromaDB.
- **Phase 1e** (3-4 days): Docker hardening — Full stack reproducible locally via `docker-compose up`. Developers can spin up production-like environment with one command.

---

## Architectural Decision: Unified Workflow Endpoint

**Decision (2026-05-27)**: Instead of separate endpoints for Orchestrator (`/api/score_jobs`) and Tailor (`/api/evaluate_job/{job_id}`), implement a single unified `/api/workflows/search-jobs` endpoint that orchestrates the entire pipeline via LangGraph.

**Rationale**:
- Reduces API surface complexity — clients invoke once, receive complete results
- Leverages LangGraph as primary orchestrator (not just CLI/Streamlit)
- Simplifies error handling — per-job error tracking within single response
- Enables future enhancements (pausable workflows, HITL approval gates) more naturally
- LangGraph state mutations and conditional logic already proven in CLI/Streamlit

**Impact on FR-005 and FR-014**: Now served by single endpoint `/api/workflows/search-jobs` (POST) which returns `OrchestrateResponse` with all_jobs (with match_scores and analysis), shortlisted_jobs (with evaluations), and rejected_jobs.

**Implementation Cleanup (2026-05-27)**: Removed intermediate/dead endpoints that were superseded by the unified workflow:
- Removed `POST /api/score_jobs` (individual job scoring endpoint)
- Removed `POST /api/evaluate_job/{job_id}` (individual evaluation endpoint)
- Removed `POST /api/orchestrate` (separate orchestration endpoint)
- Removed corresponding test cases for dead endpoints
- All functionality preserved in unified `/api/workflows/search-jobs` endpoint; API surface simplified from 5 job-related endpoints to 2 (scout + unified workflow)

## Notes for Downstream Steps

**Forward to `/10x-tech-stack-selector` or `/10x-stack-assess`** (not in PRD, but relevant to next step):

- FastAPI is the selected backend framework (locked for Phase 1).
- PostgreSQL + pgvector is the selected database (locked for Phase 1).
- LangGraph is the primary orchestration layer (locked for Phase 1 via `/api/workflows/search-jobs`).
- React or Next.js for frontend (open for selection in tech-stack phase).
- Docker Compose for local orchestration (locked for Phase 1).
- No cloud hosting; local-only deployment (locked).
- No enterprise auth integrations (OAuth, SSO); local JWT only (locked).
