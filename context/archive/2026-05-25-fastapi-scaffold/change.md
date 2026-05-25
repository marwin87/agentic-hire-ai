---
id: fastapi-scaffold
title: FastAPI Server Scaffold
status: archived
created: 2026-05-25
updated: 2026-05-25
archived_at: 2026-05-25T16:45:00Z
roadmap_id: F-01
prd_refs:
  - FR-004 (Scout endpoint)
  - FR-005 (Orchestrator endpoint)
  - FR-006 (Validate endpoint)
  - FR-010 (Docker Compose setup)
unlocks:
  - S-01 (user-signup-auth)
  - S-02 (user-login-refresh)
  - S-03 (user-cv-upload)
  - S-04 (scout-api-endpoint)
  - S-05 (validate-jobs-endpoint)
  - S-06 (orchestrator-api-endpoint)
  - S-07 (tailor-api-endpoint)
  - S-08 (user-job-list)
  - S-09 (user-evaluations)
prerequisites: []
parallel_with:
  - postgresql-pgvector-setup
blockers: []
---

# FastAPI Server Scaffold (F-01)

## Summary

Establish the FastAPI HTTP server as the primary application layer, with async-refactored agents and working endpoint handlers. This is the foundational infrastructure change that unblocks all downstream API slices (auth, agent endpoints, data persistence).

## Context

Currently, agents (Scout, Orchestrator, Tailor) are invoked synchronously via CLI (main.py) or embedded in Streamlit UI. The system has no HTTP API. This change converts the agent layer to async-compatible FastAPI endpoints, enabling multi-user request handling, state isolation, and downstream auth/database integration.

## Key Decisions Made

| Decision | Choice | Why | Source |
|----------|--------|-----|--------|
| Async strategy | Refactor agents to full async (ainvoke patterns) | True async execution scales better than thread pools; matches FastAPI best practices; enables future queue-based workers | User input |
| Server port | 8000 | Standard OpenAPI convention; Swagger docs at /docs; assumes OrioSearch can relocate from 8000 or run external | User input |
| Code organization | src/api/ directory structure | Mirrors existing src/ pattern; scales to many route files; clear separation from agent core | User input |
| Endpoint scope | Full agents wired (Scout, Validate, Orchestrator, Tailor all working) | Working API from Phase 1 completion; not just stubs. Downstream phases extend with user context, data persistence | User input |
| Error format | Structured JSON (error, detail, code) | Machine-parseable; matches Pydantic validation; enables client-side handling | User input |
| Docker orchestration | New 'api' service alongside existing 'app' (Streamlit) | Parallel services; independent scaling; clean separation | User input |

## Scope

### In Scope
- FastAPI application bootstrap with dependency injection
- Async refactor of Scout, Validate, Orchestrator, Tailor agents
- HTTP tool conversion (requests → httpx.AsyncClient)
- Working POST endpoints: `/search_jobs`, `/validate_jobs`, `/score_jobs`, `/evaluate_job/{job_id}`
- Health check endpoint
- Error handling middleware with structured responses
- Docker Compose service for FastAPI (port 8000)
- Request/response schema definitions
- Basic logging & observability plumbing

### Out of Scope
- Authentication / JWT (that's F-03)
- User data isolation / database persistence (that's F-02)
- Frontend / UI (React/Next.js is Phase 1b+)
- Rate limiting, metrics, observability tooling
- Production hardening, security headers, CORS
- WebSocket support or async streaming responses
- Deployment to cloud (local Docker Compose only)

## Implementation Approach

**Five phases of progressive integration:**

1. **Phase 1** — FastAPI scaffold: app initialization, middleware, dependency injection, error handling
2. **Phase 2** — Scout agent async refactor: convert to ainvoke, replace requests with httpx
3. **Phase 3** — Validation & Orchestrator async refactor: handle Chroma sync limitation
4. **Phase 4** — Tailor agent async refactor and route wiring: agents → endpoints
5. **Phase 5** — Docker & testing: Compose integration, health checks, endpoint verification

Each phase is incrementally testable:
- Phase 1 → health check passes
- Phase 2 → Scout endpoint returns jobs
- Phase 3 → Validation filters jobs, Orchestrator scores
- Phase 4 → Full workflow via POST requests
- Phase 5 → `docker-compose up` runs full stack

## Critical Implementation Details

### Async/Sync Bridging Strategy

The codebase is 100% synchronous (no async/await exists yet). All agents currently use `.invoke()` on LLMs and tools. Strategy:

- Replace all `.invoke()` → `.ainvoke()` in agent callables
- Replace `requests` library → `httpx.AsyncClient` for HTTP calls
- Replace `time.sleep()` → `asyncio.sleep()`
- **Chroma blocker**: ChromaDB has no async API; wrap `get_context()` calls in `asyncio.to_thread()` to run on thread pool without blocking event loop
- Update LangGraph invocation from `.invoke()` → `.ainvoke()`

This keeps agent *logic* unchanged while making *execution* async.

### Async Factory Initialization

`AgentFactory` is currently a singleton getter that initializes LLMs and agents synchronously. For FastAPI:

- Keep factory initialization synchronous (happens once at app startup via Lifespan events)
- Agents' `__call__` methods become async
- FastAPI endpoints await the async agent execution
- No need to refactor factory itself or make it async-aware

### State Management & Request Isolation

Each HTTP request gets its own `AgenticHireState` instance:

```python
# FastAPI endpoint pattern
@app.post("/search_jobs")
async def search_jobs(request: SearchJobsRequest):
    factory = get_agent_factory()
    
    # Build fresh state for this request
    state = {
        "resume_context": "...",  # Will come from user's CV in Phase 2/3
        "target_criteria": request.criteria,
        "found_jobs": [],
        ...
    }
    
    # Invoke async graph with isolated state
    result = await factory.scout(state)
    return result
```

Requests don't share state — no concurrency issues. Each request is independent.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Server (Port 8000)                                   │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ GET /health  │ POST         │ POST         │ POST           │
│ (liveness)   │ /search_jobs │ /validate    │ /score_jobs    │
│              │ (Scout)      │ _jobs        │ (Orchestrator) │
│              │              │ (Validate)   │                │
└──────────────┴──────────────┴──────────────┴────────────────┘
       ▲               ▲               ▲               ▲
       │               │               │               │
       │          ┌────────────────────────────────┐   │
       │          │ AgentFactory (singleton)        │   │
       │          │ - ScoutAgent (async)            │   │
       └──────────┤ - JobValidator (async)          ├───┘
                  │ - OrchestratorAgent (async)     │
                  │ - TailorAgent (async)           │
                  │ - CVVectorManager (sync→thread) │
                  └────────────────────────────────┘
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
        LangChain      httpx.        Chroma
        OpenAI LLM    AsyncClient    (wrapped)
```

## Implementation Checklist

### Phase 1: FastAPI Bootstrap
- [ ] 1.1 Add FastAPI, httpx, uvicorn to dependencies
- [ ] 1.2 Create `src/api/` directory structure
- [ ] 1.3 Initialize FastAPI app with `src/api/main.py`
- [ ] 1.4 Set up dependency injection (`src/api/dependencies.py`)
- [ ] 1.5 Add error handling middleware and structured response models
- [ ] 1.6 Create health check endpoint
- [ ] 1.7 Test: GET /health responds with 200 OK

### Phase 2: Scout Agent Async Refactor
- [ ] 2.1 Update `src/agents/scout.py` — make `__call__` async
- [ ] 2.2 Replace all `invoke()` calls → `ainvoke()`
- [ ] 2.3 Update `src/tools/search.py` — convert job_search_tool to async httpx
- [ ] 2.4 Update `src/tools/scrape.py` — convert scrape_webpage_tool to async httpx
- [ ] 2.5 Replace `time.sleep()` → `asyncio.sleep()` in scout
- [ ] 2.6 Create POST endpoint `/search_jobs` that awaits scout
- [ ] 2.7 Test: POST /search_jobs with criteria returns job list

### Phase 3: Validation & Orchestrator Async Refactor
- [ ] 3.1 Update `src/tools/job_validator.py` — make async, use httpx, asyncio.sleep
- [ ] 3.2 Update `src/agents/orchestrator.py` — make async, wrap Chroma in asyncio.to_thread
- [ ] 3.3 Update `validate_and_limit_jobs_node` in `src/graph.py` to be async
- [ ] 3.4 Create POST endpoint `/validate_jobs` (consumes found_jobs, returns valid + rejected)
- [ ] 3.5 Create POST endpoint `/score_jobs` (Orchestrator scoring with RAG)
- [ ] 3.6 Test: POST /validate_jobs filters invalid; POST /score_jobs returns scores

### Phase 4: Tailor Agent & Endpoint Wiring
- [ ] 4.1 Update `src/agents/tailor.py` — make async
- [ ] 4.2 Create POST endpoint `/evaluate_job/{job_id}` that awaits tailor
- [ ] 4.3 Wire endpoints into a complete workflow (search → validate → score → evaluate)
- [ ] 4.4 Test: Full workflow: POST /search_jobs → /validate_jobs → /score_jobs → /evaluate_job

### Phase 5: Docker Integration & Testing
- [ ] 5.1 Update Dockerfile to include `src/api/main.py` and uvicorn
- [ ] 5.2 Add new 'api' service to `docker-compose.yml` (port 8000)
- [ ] 5.3 Add health check for FastAPI service in Compose
- [ ] 5.4 Verify volumes (CV data, chroma_db) mounted correctly
- [ ] 5.5 Test: `docker-compose up` starts both Streamlit (8501) and FastAPI (8000)
- [ ] 5.6 Test: curl http://localhost:8000/health returns 200
- [ ] 5.7 Verify: POST endpoints respond correctly to sample requests

## Success Criteria

### Automated Verification

- [ ] All async/await syntax is valid — `uv run mypy src/agents/ src/api/` passes strict type checking
- [ ] Dependencies resolve — `uv sync` completes without conflicts
- [ ] Unit tests pass — `uv run pytest tests/test_graph.py` (agent logic tests)
- [ ] Health endpoint works — `curl http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] FastAPI docs generated — `curl http://localhost:8000/docs` returns Swagger UI
- [ ] Docker image builds — `docker build -t agentic-hire-ai:fastapi .` succeeds
- [ ] Compose stack starts — `docker-compose up` brings up api + app services without errors

### Manual Verification

- POST /search_jobs with sample criteria returns jobs (via curl or Postman)
- POST /validate_jobs filters dead links and returns valid subset
- POST /score_jobs returns match scores (0.0–1.0) for each job
- POST /evaluate_job/{id} returns evaluation summary
- Full workflow chain works: search → validate → score → evaluate
- Error responses are structured JSON with `error`, `detail`, `code` fields
- Concurrent requests (multiple curl calls) don't interfere with each other
- Docker Compose logs show both Streamlit and FastAPI services healthy
- Agents produce same-quality results as prior CLI/Streamlit version (regression test on sample CV)

**Implementation Note**: After completing Phase 5 and all automated verification passes, pause for manual confirmation from the human that the manual testing was successful before marking F-01 complete.

## Testing Strategy

### Unit Tests

- Async agent callables: mock LLMs and tools, verify ainvoke patterns
- Error responses: verify structured error format for validation failures, timeouts, agent errors
- Dependency injection: verify factory singleton works with FastAPI app lifecycle

### Integration Tests

- End-to-end workflow via HTTP: POST requests through all phases
- State isolation: two concurrent requests don't share state
- Tool replacement (httpx vs requests): verify jobs fetched correctly via async httpx

### Manual Testing

- Local curl/Postman requests to each endpoint
- Docker Compose integration: full stack runs, services communicate
- Regression test on sample CV: Orchestrator and Tailor produce same outputs as prior system

## Migration Notes

**No data migration needed** — Phase 1 is foundational infrastructure, not a data refactor. Existing ChromaDB and CSV files remain unchanged. Future phases (F-02 PostgreSQL setup) will handle data migration.

## Docker Changes

**Current:** Single 'app' service running Streamlit (port 8501)

**After F-01:**
- Streamlit 'app' service continues to run (port 8501)
- New 'api' service runs FastAPI (port 8000)
- Shared volumes: ./data/cv and chroma_db
- Both services see same environment variables (OPENROUTER_API_KEY, etc)

```yaml
services:
  app:  # Existing Streamlit service (unchanged)
    ...

  api:  # New FastAPI service
    build: .
    command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      AGENTIC_HIRE_OPENROUTER_API_KEY: ${AGENTIC_HIRE_OPENROUTER_API_KEY}
      ...
    volumes:
      - ./data/cv:/app/data/cv
      - chroma_db:/app/data/chroma_db
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## References

- Research: `context/changes/fastapi-scaffold/research.md`
- Roadmap: `context/foundation/roadmap.md` (F-01 section)
- PRD: `context/foundation/prd.md` (Phase 1a, Scope of Change)
- Current agents: `src/agents/` (scout.py, orchestrator.py, tailor.py)
- Current tools: `src/tools/` (search.py, scrape.py, job_validator.py, vectordb.py)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: FastAPI Bootstrap

#### Automated

- [ ] 1.1 Add FastAPI, httpx, uvicorn dependencies
- [ ] 1.2 Create src/api/ directory structure with __init__.py
- [ ] 1.3 Initialize FastAPI app in src/api/main.py
- [ ] 1.4 Set up dependency injection in src/api/dependencies.py
- [ ] 1.5 Add error middleware and response models
- [ ] 1.6 Create health check endpoint
- [ ] 1.7 Type checking passes: uv run mypy src/api/ src/agents/

#### Manual

- [ ] 1.8 GET /health responds with 200 OK

### Phase 2: Scout Agent Async Refactor

#### Automated

- [ ] 2.1 ScoutAgent.__call__ is async
- [ ] 2.2 All invoke() replaced with ainvoke() in scout
- [ ] 2.3 job_search_tool uses httpx.AsyncClient
- [ ] 2.4 scrape_webpage_tool uses httpx.AsyncClient
- [ ] 2.5 All time.sleep() replaced with asyncio.sleep()
- [ ] 2.6 POST /search_jobs endpoint created
- [ ] 2.7 Type checking passes: uv run mypy src/agents/

#### Manual

- [ ] 2.8 POST /search_jobs returns job list with sample criteria

### Phase 3: Validation & Orchestrator Async Refactor

#### Automated

- [ ] 3.1 JobValidator async, httpx, asyncio.sleep
- [ ] 3.2 OrchestratorAgent async, Chroma wrapped in asyncio.to_thread
- [ ] 3.3 validate_and_limit_jobs_node is async
- [ ] 3.4 POST /validate_jobs endpoint created
- [ ] 3.5 POST /score_jobs endpoint created
- [ ] 3.6 Type checking passes: uv run mypy src/

#### Manual

- [ ] 3.7 POST /validate_jobs filters correctly
- [ ] 3.8 POST /score_jobs returns match scores (0.0–1.0)

### Phase 4: Tailor Agent & Endpoint Wiring

#### Automated

- [ ] 4.1 TailorAgent.__call__ is async
- [ ] 4.2 POST /evaluate_job/{job_id} endpoint created
- [ ] 4.3 Full workflow wiring verified
- [ ] 4.4 Type checking passes: uv run mypy src/

#### Manual

- [ ] 4.5 Full workflow (search → validate → score → evaluate) works

### Phase 5: Docker Integration & Testing

#### Automated

- [ ] 5.1 Dockerfile updated to run FastAPI via uvicorn
- [ ] 5.2 docker-compose.yml updated with 'api' service
- [ ] 5.3 Health check for FastAPI service added
- [ ] 5.4 docker build succeeds
- [ ] 5.5 docker-compose up starts both services without errors

#### Manual

- [ ] 5.6 curl http://localhost:8000/health returns 200 OK
- [ ] 5.7 All POST endpoints respond correctly via Docker
- [ ] 5.8 Regression test: Agent outputs match prior system quality
