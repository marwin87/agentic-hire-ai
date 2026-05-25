---
project: AgenticHire AI — Production Readiness Refactor
context_type: brownfield
checkpoint:
  current_phase: 8
  phases_completed: [1, 2, 3, 4, 5, 6, 7]
  frs_drafted: 14
  quality_check_status: accepted
updated: 2026-05-19
---

# Shape Notes: AgenticHire AI Production Readiness

## Current System

AgenticHire AI is a multi-agent job application system built on LangGraph. Today it runs as:
- **Execution model**: Single-threaded Streamlit UI or CLI invocation (main.py)
- **Vector storage**: ChromaDB local instance
- **User model**: Anonymous, one-user-at-a-time workflow
- **External integrations**: OrioSearch (job discovery), OpenRouter (LLM reasoning), Vision LLM (CV parsing)
- **Agent workflow**: Autonomous end-to-end execution (Scout → Validate → Orchestrate → Tailor)

The system successfully handles job search, CV matching via RAG, and job evaluation. It is production-grade in agent logic but is fragile at the infrastructure layer — no multi-tenancy, no persistent state across sessions, no access control.

## Vision & Problem Statement

**The binding problem**: Scale AgenticHire AI from a local developer demo into a secure, production-ready, multi-tenant agent application.

The refactoring is not a collection of independent features; the enhancements form a strict dependency chain:

- Human-in-the-Loop (HITL) dashboard for paused workflows requires an asynchronous backend to handle state interruption.
- Asynchronous backend state persistence requires a relational database (not ChromaDB).
- Multi-user state storage requires access control to prevent data leaks.
- High-value compute agents (Resume Tweak) require auth to prevent unauthorized API token exploitation.

**The architectural shift**:
1. **Phase 1 (Bedrock)**: Migrate from Streamlit/ChromaDB/CLI to FastAPI + PostgreSQL+pgvector + JWT auth + Docker Compose. The agent workflow remains unchanged; execution becomes asynchronous and multi-user.
2. **Phase 2 (Workflow)**: Introduce HITL breakpoint using LangGraph's PostgresSaver state interruption. After Scout and Orchestrator, the graph pauses; user approves selected jobs; graph resumes to Tailor.
3. **Phase 3 (Capability)**: Add Resume Tweak Agent downstream of user approval — generates ATS-optimized resume refinement suggestions per job.

**What stays intact**:
- Core agent logic, prompts, scoring algorithms
- Multimodal vision pipeline (PDF → Images → Vision LLM → embeddings)
- External API integrations (OrioSearch, OpenRouter, Vision LLM)
- Data flow logic (only destinations and orchestration layer change)

**What is deprecated**:
- CLI (main.py) — fully replaced by FastAPI endpoints
- Streamlit UI (ui.py) — replaced by modern React/Next.js frontend

## User & Persona

**Primary persona**: Individual software engineers and AI developers managing their own high-end job search.

**Access model**: Email/Password signup → JWT-secured workspace. No multi-tenant enterprise features (teams, RBAC, SSO, organization spaces) — individual accounts only, laser-focused on solo user workflows.

**Why this scoping matters**: Because the target audience runs this locally via Docker Compose, authentication is straightforward (local JWT + bcrypt). No cloud scale concerns (load balancers, Kubernetes, serverless), zero infrastructure costs (users provide API keys, run compute locally). The codebase remains architecturally ready for future cloud migration, but that is not required for MVP.

---

## Access Control

**Current**: Anonymous, one user per invocation.

**Planned**: 
- User signup via email + password (hashed with bcrypt)
- JWT token-based session management (issued per login)
- All user-created data (uploaded CVs, discovered jobs, evaluation criteria) stored in PostgreSQL, keyed by user_id
- Token scope: limited to the authenticated user's own data namespace

**No new roles**: Individual workspace model only. No admin roles, no shared access, no organization tiers for MVP.

---

## Phase 1 Sub-Phases

Phase 1 (all components mandatory) is split into sequential, testable increments:

- **Phase 1a**: Backend scaffold (FastAPI server, PostgreSQL container, Docker Compose orchestration)
- **Phase 1b**: Auth layer (JWT tokens, bcrypt hashing, signup/login endpoints)
- **Phase 1c**: Agent porting (Scout, Validate, Orchestrator moved to FastAPI endpoints, results → Postgres)
- **Phase 1d**: Vision + pgvector (CV ingestion pipeline refactored to pgvector inserts)
- **Phase 1e**: Docker hardening (full stack reproducible locally via `docker-compose up`)

Each sub-phase is testable and delivers working infrastructure.

---

## Timeline Acknowledgment

**User context**: Solo developer, after-hours/weekends, now with more available time.

**Estimated effort**: 8–12 weeks of sustained development (not 3-week sprints; this requires consistent, dedicated work).

Acknowledged on 2026-05-19: User understands and accepts the sustained-effort cost for this multi-phase refactor. Phase 1 sub-phases are non-optional.

---

## Open Questions (to resolve in later phases)

- Frontend framework choice (React vs Next.js vs other)?
- Database migration strategy for any existing data?
- Exact Resume Tweak Agent output format (markdown diff, bulleted list, other)?
- Monitoring/logging strategy post-deployment?

---

## Functional Requirements

Phase 1 FRs (all mandatory for 4-week MVP):

**New Capabilities:**
- FR-001: User can sign up with email + password. Priority: must-have. Change: new
- FR-002: User can log in with JWT token. Priority: must-have. Change: new
- FR-003: User can upload and store CV (isolated by user_id). Priority: must-have. Change: new
- FR-004: Scout Agent can be invoked via FastAPI endpoint. Priority: must-have. Change: modified
- FR-005: Orchestrator can be invoked via FastAPI endpoint. Priority: must-have. Change: modified
- FR-006: Validate can be invoked via FastAPI endpoint. Priority: must-have. Change: modified
- FR-007: User can view personal job list (database-backed). Priority: must-have. Change: new
- FR-008: User can view personal evaluation scores. Priority: must-have. Change: new
- FR-009: CV embeddings stored in pgvector. Priority: must-have. Change: modified
- FR-010: Full stack runs in Docker Compose locally. Priority: must-have. Change: new

**Preserved Capabilities:**
- FR-011: Scout discovers jobs via OrioSearch API (logic unchanged). Priority: must-have. Change: preserved
- FR-012: Orchestrator scores jobs via OpenRouter (prompts unchanged). Priority: must-have. Change: preserved
- FR-013: Vision pipeline parses CV with same quality (PDF → Images → Vision LLM). Priority: must-have. Change: preserved
- FR-014: Tailor generates evaluation text (reasoning unchanged, now persisted). Priority: must-have. Change: preserved

---

## User Stories (Primary Path)

**US-01: Developer uploads CV and authenticates**

```
Given: A developer has Docker Compose running locally
When: They visit http://localhost:3000 and sign up with email + password
Then: They are logged in with a JWT token, and can upload their CV PDF
And: The system parses the CV, generates embeddings, and stores them in pgvector
```

Acceptance criteria:
- Signup form validates email format and password strength
- Login persists JWT in session
- CV upload accepts PDF, shows processing status, completes within 30 seconds
- Embeddings match quality of prior ChromaDB version (verified via test set)

---

## Business Logic

**Domain rule (preserved)**: Multi-user job matching using RAG-based semantic similarity between CV and job descriptions. Each user has an isolated matching context — no data leakage between users.

The scoring algorithm (0.0–1.0 relevance) and agent reasoning remain unchanged. The only addition is **user_id isolation**: every job, CV chunk, and score is tagged with user_id in the database.

---

## Non-Functional Requirements

- **Data Isolation**: One user cannot see another user's CVs, jobs, or scores. Enforced at database schema (user_id foreign keys) and API layer (JWT validation on all endpoints).
- **Auth Security**: Passwords hashed with bcrypt (cost factor ≥ 12); JWT tokens include expiration; no plaintext secrets in code or Docker images.
- **Embedding Quality**: CV → pgvector embeddings must produce same semantic search results as prior ChromaDB version. Verified via regression test on sample CVs.
- **Local Performance**: End-to-end workflow (upload CV, search jobs, score) completes in <2 minutes on developer machine (modern laptop, 8GB RAM).
- **Agent Logic Fidelity**: Scout, Orchestrator, Tailor outputs identical to prior system. No prompt changes. No scoring algorithm changes.

---

## Constraints & Preserved Behavior

**Deprecation (intentional breaking change, acceptable for personal open-source project):**
- CLI (main.py) — fully replaced by FastAPI endpoints
- Streamlit UI (ui.py) — fully replaced by React/Next.js frontend
- ChromaDB — fully replaced by PostgreSQL + pgvector

**Preserved:**
- Scout agent connection to OrioSearch API (same payload, new destination: Postgres)
- OpenRouter LLM gateway (same models, same prompts)
- Vision LLM CV parsing logic (same PDF handling, same embeddings quality)
- Tailor agent evaluation reasoning (same prompts, now database-backed)

**Data migration**: Fresh start (no data import from old system).

---

## Product Type & Scale

**Product type**: Web application (Streamlit → React/FastAPI, same type).

**User base**: Individual software engineers managing their own job search (no change).

**Target scale**: Single-machine local deployment (no cloud scaling required).

---

## Non-Goals (Explicitly NOT in Phase 1 MVP)

- No enterprise RBAC, team spaces, or multi-organization support
- No cloud hosting, Kubernetes, or serverless infrastructure
- No API rate-limiting or usage monitoring
- No analytics, telemetry, or observability
- Phase 2 (Human-in-the-Loop approval workflow) — optional, not MVP
- Phase 3 (Resume Tweak Agent) — optional, not MVP
- No migration tool for existing ChromaDB data
- No reverse-compatibility with CLI or Streamlit UI

---

## Socrates Round (Condensed)

All FRs stand as written. No counter-arguments surface show-stoppers. The 4-week timeline is tight but achievable for Phase 1 with focused execution.

---

## Quality Cross-Check

| Element | Status | Notes |
|---------|--------|-------|
| Access Control | ✓ Present | Email/Password + JWT auth, per-user isolation |
| Business Logic (one-sentence) | ✓ Present | Multi-user RAG-based job matching with user isolation |
| Project artifacts | ✓ Present | shape-notes.md with frontmatter checkpoint |
| Timeline-cost acknowledged | ✓ Present | 4 weeks, solo developer, Phase 1 mandatory |
| Non-Goals | ✓ Present | 7 explicit non-goals (no enterprise, no cloud, Phase 2+3 optional) |
| Preserved behavior | ✓ Present | Agent logic, vision pipeline, external APIs stay intact |

**Quality check status**: `accepted` — all elements present, no gaps.

---

## Next Step

Shape complete. Ready for `/10x-prd` to generate the formal PRD from these notes.
