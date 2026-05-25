# FastAPI Server Scaffold (F-01) — Plan Brief

> Full plan: `context/changes/fastapi-scaffold/plan.md`
> Research: (Auto-researched; see agent output above)

## What & Why

We're converting AgenticHire AI from a synchronous CLI/Streamlit application to an async HTTP API server. Currently, agents (Scout, Orchestrator, Tailor) are invoked synchronously via `main.py` or embedded in the Streamlit UI. No multi-user request handling, no state isolation, no database persistence — the system can't scale beyond a single demo.

**F-01 establishes FastAPI as the primary application layer**, with fully async-refactored agents and working endpoint handlers. This is the foundational infrastructure that unblocks all downstream API slices (auth in F-03, database in F-02, agent endpoints in S-04 through S-07).

## Starting Point

The codebase already has:
- **LangGraph agents** (Scout, Orchestrator, Tailor) that are synchronous callables
- **Tools** for job search, webpage scraping, and validation using `requests` (blocking)
- **ChromaDB** for vector storage (sync-only API)
- **Docker + Compose** setup for Streamlit (port 8501)
- **Pydantic configuration** management (ready for HTTP layer)

What's missing: No HTTP API, no async execution, no multi-request isolation.

## Desired End State

A FastAPI server running on port 8000 with:
- **Health check endpoint** (`GET /health`)
- **Four working agent endpoints**:
  - `POST /search_jobs` — Scout agent (finds jobs)
  - `POST /validate_jobs` — Filters dead/expired jobs
  - `POST /score_jobs` — Orchestrator (semantic relevance scoring with RAG)
  - `POST /evaluate_job/{job_id}` — Tailor (evaluation summaries)
- **All agents refactored to async** (ainvoke patterns throughout)
- **HTTP tools replaced with async httpx** (requests → httpx.AsyncClient)
- **Structured JSON error responses** (all endpoints)
- **Docker Compose orchestrates both Streamlit (8501) and FastAPI (8000)**
- **Type checking passes** (strict mypy)
- **Agents produce identical outputs** to prior system (regression verified)

Verification: Health endpoint responds, all POST endpoints work with sample data, full workflow chain completes, Docker Compose brings up full stack.

## Key Decisions Made

| Decision | Choice | Why | Source |
|----------|--------|-----|--------|
| **Async strategy** | Refactor agents to full async (ainvoke patterns) | True async execution; scalable; matches FastAPI best practice; enables future queue workers | User choice |
| **Port** | 8000 | Standard OpenAPI convention; Swagger at /docs | User choice |
| **Structure** | src/api/ directory | Mirrors existing src/ pattern; scales to many endpoints | User choice |
| **Scope** | Full agents wired (working endpoints) | End-to-end API from day 1, not just stubs | User choice |
| **Errors** | Structured JSON (error, detail, code) | Machine-parseable; matches Pydantic validation format | User choice |
| **Docker** | New 'api' service alongside Streamlit 'app' | Parallel services; independent scaling; no breaking changes | User choice |

## Scope

**In scope**:
- FastAPI bootstrap + dependency injection
- Async refactor of all four agents (Scout, Validate, Orchestrator, Tailor)
- HTTP tool conversion (requests → httpx)
- Working POST endpoints for all agents
- Error handling middleware
- Docker Compose FastAPI service
- Type-safe request/response schemas
- Basic logging and observability plumbing

**Out of scope**:
- Authentication / JWT (that's F-03)
- User data persistence / PostgreSQL (that's F-02)
- Frontend / React UI (Phase 1b+)
- Rate limiting, metrics, advanced observability
- Production hardening, security headers, CORS
- WebSocket, streaming, background jobs
- Cloud deployment, Kubernetes

## Architecture / Approach

```
┌─────────────────────────────────────────────┐
│ FastAPI Server (Port 8000)                   │
│ /health  /search_jobs  /validate_jobs        │
│ /score_jobs  /evaluate_job/{id}              │
└─────────────────────────────────────────────┘
           ▲          ▲          ▲
           │    ┌──────────────┐ │
           │    │ AgentFactory │ │
           │    │ (singleton)  │ │
           │    └──────────────┘ │
           │     /   |   |   \   │
        Scout   Valid Orch. Tailor (async)
         (HTTP: httpx.AsyncClient)
           │      │     │     │
        LLM    LLM   LLM+Chroma  LLM
        (ainvoke patterns throughout)
```

**Async strategy**: Refactor all agent `__call__` methods from sync to async. Replace:
- LLM `.invoke()` → `.ainvoke()`
- `requests` → `httpx.AsyncClient`
- `time.sleep()` → `asyncio.sleep()`
- Chroma (sync-only) → wrapped in `asyncio.to_thread()`

No agent logic changes; only execution model becomes async.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|-------|------------------|----------|
| 1. Bootstrap | FastAPI app, middleware, health endpoint | Dependency conflicts, import errors |
| 2. Scout async | Scout agent refactored, httpx tools, /search_jobs endpoint | LLM ainvoke integration, async tool binding |
| 3. Validation & Orchestrator async | JobValidator, OrchestratorAgent async, Chroma wrapping, /validate_jobs and /score_jobs | Chroma sync limitation (mitigated by asyncio.to_thread) |
| 4. Tailor async & wiring | TailorAgent async, /evaluate_job endpoint, full workflow integration | State isolation, concurrent request handling |
| 5. Docker & testing | Dockerfile update, docker-compose service, health checks, manual verification | Docker networking, volume mounting, service coordination |

**Prerequisites**: None — F-01 has no upstream dependencies.  
**Estimated effort**: ~3 sessions across 5 phases (each phase ~1–2 hours of implementation + testing).

## Open Risks & Assumptions

- **Async refactoring scope**: ~15 `invoke()` calls to convert to `ainvoke()` across four agents. Research completed; specific line references identified.
- **Chroma sync limitation**: No native async API. Mitigated by `asyncio.to_thread()` wrapper (offloads to thread pool). Acceptable for local MVP.
- **LangGraph async integration**: LangGraph supports `.ainvoke()` for async node execution. Verified; low risk.
- **httpx library**: Replacement for `requests`; async-first. Mature library; low risk.
- **Concurrent request isolation**: Each request gets fresh AgenticHireState. No shared state; low risk of concurrency bugs.
- **Agent output quality**: Agents produce identical results to prior system (same prompts, same logic). Regression test on sample CV verifies.

## Success Criteria (Summary)

1. **Type checking** — `uv run mypy src/` passes strict mode
2. **Health endpoint** — `GET /health` returns 200 OK
3. **Agent endpoints** — All four POST endpoints respond with correct schemas
4. **Full workflow** — Chain all endpoints: search → validate → score → evaluate
5. **Docker Compose** — `docker-compose up` starts both FastAPI (8000) and Streamlit (8501)
6. **Regression** — Sample CV scoring/evaluation matches prior CLI/Streamlit system
7. **Concurrency** — Multiple concurrent requests don't interfere with each other
