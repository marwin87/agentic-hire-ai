# FastAPI Server Scaffold (F-01) — Implementation Plan

## Overview

Convert the agent layer from synchronous CLI/Streamlit invocation to async-enabled FastAPI HTTP endpoints. This foundational infrastructure change enables multi-user request isolation, state persistence, and downstream auth/database integration.

Currently, agents (Scout, Orchestrator, Tailor) are synchronous callables invoked via main.py (CLI) or embedded in ui.py (Streamlit). No HTTP API exists. F-01 establishes FastAPI as the primary application layer with fully async-refactored agents and working endpoint handlers.

## Current State Analysis

### Existing Agent Infrastructure
- **Location**: `src/agents/` (scout.py, orchestrator.py, tailor.py, agents.py)
- **Pattern**: Synchronous callables (`__call__` methods) that invoke LLMs via `.invoke()`
- **Invocation**: LangGraph state machine in `src/graph.py` uses synchronous `.invoke()`
- **Tools**: Synchronous HTTP requests via `requests` library (search.py, scrape.py, job_validator.py)
- **State**: `AgenticHireState` TypedDict with job lists, evaluation results (no async context needed)
- **Factory**: `AgentFactory` singleton in `src/agents/agents.py` for central LLM/agent initialization
- **Vector DB**: ChromaDB via `src/tools/vectordb.py` — synchronous only (no async API)

### Key Sync Callables That Need Async Conversion
1. **ScoutAgent** (`src/agents/scout.py:47`) — `__call__(state)` → needs `async __call__(state)`
2. **OrchestratorAgent** (`src/agents/orchestrator.py:28`) — similar async conversion
3. **TailorAgent** (`src/agents/tailor.py:17`) — similar async conversion
4. **JobValidator.is_job_valid()** (`src/tools/job_validator.py:35`) — HTTP check + LLM invoke
5. **validate_and_limit_jobs_node** (`src/graph.py:45`) — filtering logic, becomes async
6. **Tools**: `job_search_tool`, `scrape_webpage_tool` — replace `requests` with `httpx.AsyncClient`

### Async Gaps to Bridge
- **No async/await** exists in current codebase (100% sync)
- **Requests library** blocks event loop; must replace with `httpx` (async HTTP)
- **Chroma** has no async API; wrap in `asyncio.to_thread()` to offload to thread pool
- **LangChain LLM invoke** has async equivalent (`.ainvoke()`); must use throughout
- **time.sleep()** blocks event loop; replace with `asyncio.sleep()`

### Docker Situation
- **Current**: Single 'app' service running Streamlit (port 8501)
- **Dockerfile**: Multi-stage build for Streamlit; EXPOSE 8501
- **Compose**: Single 'app' service; volumes for data/cv and chroma_db
- **Changes needed**: Add new 'api' service (FastAPI on 8000); keep Streamlit running

## Desired End State

After F-01 completion:
- FastAPI server running on port 8000 (async request handling)
- Health check endpoint (`GET /health`)
- Four working agent endpoints:
  - `POST /search_jobs` — Scout agent (finds jobs via OrioSearch)
  - `POST /validate_jobs` — Validation (filters dead links, expired postings)
  - `POST /score_jobs` — Orchestrator agent (semantic relevance scoring with RAG)
  - `POST /evaluate_job/{job_id}` — Tailor agent (evaluation summary generation)
- Structured JSON error responses (all endpoints)
- All agents refactored to async (ainvoke patterns)
- HTTP tools replaced with async httpx
- Docker Compose orchestrates both Streamlit (8501) and FastAPI (8000)
- Type checking passes (`mypy` strict mode)
- Agents produce identical outputs to prior CLI/Streamlit system (regression verified)

### Verification Method
1. **Automated**: Type checking, health endpoint response, Docker build/compose
2. **Manual**: curl requests to each endpoint, full workflow chain test, Docker Compose integration, regression test on sample CV

## Key Discoveries

- **Async refactoring is the core work**: Not just scaffolding, but converting ~15 `invoke()` calls to `ainvoke()`, replacing `requests` with `httpx`, handling Chroma's sync limitation
- **Agent logic stays unchanged**: Only execution model changes (sync → async); no prompt changes, no scoring algorithm changes
- **Factory singleton is safe**: AgentFactory initialization remains sync (happens once at app startup); agents' `__call__` methods become async
- **State isolation is automatic**: Each HTTP request gets fresh AgenticHireState; no concurrency issues
- **Test coverage exists**: `tests/test_graph.py` has agent logic tests; regression tests on sample CVs verify quality

## What We're NOT Doing

- Authentication / JWT (that's F-03: jwt-auth-middleware)
- User data persistence / PostgreSQL (that's F-02: postgresql-pgvector-setup)
- Frontend UI / React (that's Phase 1b+)
- API rate limiting, metrics, Sentry/monitoring
- Security headers, CORS, production hardening
- WebSocket support, streaming responses, background jobs
- Cloud deployment, Kubernetes, serverless
- Reverse-compatibility with CLI or Streamlit UI

## Implementation Approach

Five phases of progressive integration, each with automated + manual verification gates:

1. **Phase 1: FastAPI Bootstrap** — App init, middleware, dependency injection, health check. Unblocks Phase 2.
2. **Phase 2: Scout Agent Async** — Refactor Scout to async, replace requests→httpx, wire POST /search_jobs endpoint.
3. **Phase 3: Validation & Orchestrator Async** — Async refactor for validation and orchestrator, Chroma wrapping strategy, POST /validate_jobs and /score_jobs endpoints.
4. **Phase 4: Tailor Async & Full Wiring** — Async refactor Tailor, wire POST /evaluate_job endpoint, integrate full workflow.
5. **Phase 5: Docker Integration & Testing** — Update Dockerfile/Compose, health checks, manual verification of full stack.

Each phase is independently testable and deployable. Phase N can be reviewed before proceeding to Phase N+1.

## Critical Implementation Details

### Async/Sync Bridging Strategy

**Problem**: Agents are sync; FastAPI is async-first. Direct calling blocks event loop.

**Solution**: Refactor agents to async from the ground up:

1. **Agent `__call__` methods** — Change signature from `def __call__(state) -> dict` to `async def __call__(state) -> dict`
2. **LLM invocations** — Replace all `self.llm.invoke(messages)` with `await self.llm.ainvoke(messages)`
3. **Tool invocations** — Replace all `tool.invoke(args)` with `await tool.ainvoke(args)` (after tools are async)
4. **Blocking sleep** — Replace `time.sleep(delay)` with `await asyncio.sleep(delay)`
5. **HTTP requests** — Replace `requests.get/post()` with `httpx.AsyncClient().get/post()` (in search.py, scrape.py, job_validator.py)
6. **Chroma limitation** — Chroma has no async API. Wrap `CVVectorManager.get_context()` calls in `asyncio.to_thread()`:

```python
# In OrchestratorAgent
context = await asyncio.to_thread(
    self.vector_manager.get_context,
    search_query,
    k=3
)
```

This offloads the sync Chroma call to a thread pool, freeing the event loop.

7. **LangGraph async invocation** — Update `src/graph.py` node signatures to be async, compile graph for `.ainvoke()`:

```python
# BEFORE
workflow.add_node("scout", factory.scout)  # sync callable

# AFTER
async def async_scout_node(state):
    return await factory.scout(state)

workflow.add_node("scout", async_scout_node)  # async callable
```

Then invoke with: `result = await graph.ainvoke(initial_state)` instead of `.invoke()`.

### Agent Factory & Lifecycle

- **AgentFactory initialization** remains sync (factory.py unchanged)
- Initialization happens once at FastAPI app startup via Lifespan events
- Once initialized, agents are called async from endpoints
- Example pattern:

```python
# src/api/main.py
from contextlib import asynccontextmanager
from src.agents.agents import get_agent_factory

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize factory once
    factory = get_agent_factory()
    yield
    # Shutdown: cleanup if needed (not needed here)

app = FastAPI(lifespan=lifespan)
```

Then in endpoints:

```python
@app.post("/search_jobs")
async def search_jobs(request: SearchJobsRequest):
    factory = get_agent_factory()  # Returns cached singleton
    state = {...}
    result = await factory.scout(state)  # Call async agent
    return result
```

### Request State Isolation

Each HTTP request gets independent state:

```python
@app.post("/search_jobs")
async def search_jobs(request: SearchJobsRequest):
    # Fresh state per request — no sharing between concurrent requests
    state: AgenticHireState = {
        "resume_context": "...",
        "target_criteria": request.criteria,
        "found_jobs": [],
        "valid_jobs": [],
        "scout_runs": 0,
        # ... other fields
    }
    
    # This state is isolated to this request
    result = await factory.scout(state)
    return result
```

No concurrency issues because state is not shared. Future phases (F-02, F-03) will add user_id context, but the isolation model remains the same.

### Error Handling & Structured Responses

All endpoints return structured JSON on error:

```python
{
    "error": "validation_error",
    "detail": "Invalid job URL format",
    "code": "INVALID_JOB_URL"
}
```

Custom exception handler in middleware:

```python
# src/api/main.py
from fastapi import FastAPI
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": str(exc),
            "code": "INTERNAL_SERVER_ERROR"
        }
    )
```

Specific handlers for validation errors, timeouts, LLM failures, etc.

## Phase 1: FastAPI Bootstrap

### Overview

Initialize FastAPI application with dependency injection, error handling middleware, and basic project structure. Establish the foundation that agents will be wired into in later phases.

### Changes Required

#### 1. Dependencies (pyproject.toml)

**File**: `pyproject.toml`

**Intent**: Add FastAPI, ASGI server (uvicorn), async HTTP client (httpx), and type stubs.

**Contract**: Updated dependencies list includes:
- `fastapi` (latest)
- `uvicorn[standard]` (ASGI server)
- `httpx` (async HTTP client)
- `python-multipart` (for form data parsing)

**Changes**:
```toml
dependencies = [
    # ... existing ...
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "httpx>=0.28.0",
    "python-multipart>=0.0.9",
]
```

#### 2. FastAPI Application Entry Point

**File**: `src/api/main.py` (new file)

**Intent**: Initialize FastAPI app with middleware, error handlers, health endpoint, and async context management.

**Contract**: Module exports `app` (FastAPI instance) for uvicorn to serve. Includes:
- Lifespan context manager for startup/shutdown
- CORS middleware (permissive for local dev, will tighten in Phase 2)
- Request logging middleware
- Global exception handler for structured error responses
- GET /health endpoint returning `{"status": "ok"}`

**Signature**:
```python
from fastapi import FastAPI

app = FastAPI(title="AgenticHire AI", version="1.0.0")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

#### 3. Dependency Injection

**File**: `src/api/dependencies.py` (new file)

**Intent**: Centralize FastAPI dependency injection patterns for agent factory access and request context.

**Contract**: Exports getter functions:
- `get_factory()` → returns AgentFactory singleton
- `get_config()` → returns AppConfig singleton
- Request schema validators (Pydantic models for SearchJobsRequest, etc.)

#### 4. Response Models & Error Schemas

**File**: `src/api/schemas.py` (new file)

**Intent**: Pydantic models for request/response validation and error structures.

**Contract**: Exports:
- `SearchJobsRequest` (criteria: str, max_results: int)
- `ValidateJobsRequest` (jobs: List[JobOffer])
- `ScoreJobsRequest` (jobs: List[JobOffer])
- `EvaluateJobRequest` (job_id: str, job: JobOffer)
- `ErrorResponse` (error: str, detail: str, code: str)
- Individual agent response types

#### 5. Logging & Observability

**File**: `src/api/logging.py` (new file)

**Intent**: Set up request logging, error tracking, and structured logging for API calls.

**Contract**: Configures loguru to log:
- Incoming requests (method, path, remote addr)
- Outgoing responses (status code, response time)
- Errors with full traceback
- Agent invocations and timings

#### 6. Middleware Setup

**File**: `src/api/middleware.py` (new file)

**Intent**: Request/response timing, error handling, CORS, request ID tracking.

**Contract**: Includes:
- Timing middleware (measures request duration)
- Error response middleware (converts exceptions to structured JSON)
- Request ID injection (X-Request-ID header for tracing)
- Basic CORS (localhost only, tighten in Phase 2)

### Success Criteria

#### Automated Verification

- [ ] 1.1 `uv sync` completes without dependency conflicts
- [ ] 1.2 `uv run mypy src/api/ src/agents/` passes strict type checking
- [ ] 1.3 `uv run python -c "from src.api.main import app; print(app.title)"` outputs "AgenticHire AI"
- [ ] 1.4 `uv run pytest tests/test_api_health.py` — health endpoint test passes

#### Manual Verification

- [ ] 1.5 `uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8000` starts without errors
- [ ] 1.6 `curl http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] 1.7 `curl http://localhost:8000/docs` returns Swagger UI HTML
- [ ] 1.8 `curl http://localhost:8000/openapi.json` returns valid OpenAPI schema

---

## Phase 2: Scout Agent Async Refactor

### Overview

Refactor Scout agent from synchronous to async execution. Replace `requests` library with async `httpx` in job search and webpage scraping tools. Wire POST /search_jobs endpoint.

### Changes Required

#### 1. ScoutAgent Async Refactor

**File**: `src/agents/scout.py`

**Intent**: Convert `__call__` method and all internal invocations to async. Maintain exact same logic and prompts; only execution model changes.

**Contract**: Method signature changes from:
```python
def __call__(self, state: AgenticHireState) -> dict[str, Any]
```
to:
```python
async def __call__(self, state: AgenticHireState) -> dict[str, Any]
```

Key changes:
- `self.llm.invoke(messages)` → `await self.llm.ainvoke(messages)` (all LLM calls)
- `tool.invoke(args)` → `await tool.ainvoke(args)` (after tools become async)
- `time.sleep(delay)` → `await asyncio.sleep(delay)`
- All interior functions that await LLM/tools must become async

**Specific line references** (from research):
- Line 129: `response = self.llm.invoke(messages)` → ainvoke
- Line 140: `raw_results = job_search_tool.invoke(...)` → ainvoke (after tool is async)
- Line 149: `raw_results = scrape_webpage_tool.invoke(...)` → ainvoke
- Line 157: `time.sleep(config.scout_rate_limit_delay)` → asyncio.sleep
- Line 185: `self.parser.parse(...)` — stays sync (no LLM involved)
- Line 208: fallback `job_search_tool.invoke()` → ainvoke

#### 2. Job Search Tool (Async HTTP)

**File**: `src/tools/search.py`

**Intent**: Convert job_search_tool from sync requests.post() to async httpx.post().

**Contract**: Tool becomes async-capable:
```python
# BEFORE
@tool
def job_search_tool(search_query: str) -> str:
    response = requests.post(config.oriosearch_base_url + "/search", json={"query": search_query})
    return response.text

# AFTER
@tool
async def job_search_tool(search_query: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            config.oriosearch_base_url + "/search",
            json={"query": search_query}
        )
    return response.text
```

LangChain tools can be async-wrapped; LLM will await them automatically.

#### 3. Scrape Webpage Tool (Async HTTP)

**File**: `src/tools/scrape.py`

**Intent**: Convert scrape_webpage_tool from sync requests.get() to async httpx.get().

**Contract**: Similar to job_search_tool, use httpx.AsyncClient for HTML fetching.

#### 4. Search Jobs Endpoint

**File**: `src/api/routes/search.py` (new file)

**Intent**: Wire POST /search_jobs endpoint that invokes ScoutAgent asynchronously.

**Contract**: Endpoint signature:
```python
@router.post("/search_jobs")
async def search_jobs(request: SearchJobsRequest) -> SearchJobsResponse:
    factory = get_factory()
    state = {
        "resume_context": "...",  # placeholder; will be user's CV in Phase 2
        "target_criteria": request.criteria,
        "found_jobs": [],
        "scout_runs": 0,
        ...
    }
    result = await factory.scout(state)
    return SearchJobsResponse(
        found_jobs=result.get("found_jobs", []),
        status=result.get("status", "")
    )
```

### Success Criteria

#### Automated Verification

- [ ] 2.1 `uv run mypy src/agents/scout.py` passes strict type checking
- [ ] 2.2 `uv run mypy src/tools/search.py src/tools/scrape.py` passes
- [ ] 2.3 `uv run pytest tests/test_scout_async.py` (new async scout tests) passes
- [ ] 2.4 `uv run black src/agents/scout.py src/tools/search.py src/tools/scrape.py --check` passes formatting

#### Manual Verification

- [ ] 2.5 `POST http://localhost:8000/search_jobs` with sample criteria returns job list
- [ ] 2.6 Response includes `found_jobs` array with JobOffer objects (id, title, company, url)
- [ ] 2.7 Concurrent requests to /search_jobs don't interfere (test with 2+ parallel curls)
- [ ] 2.8 Error response is structured JSON if request is malformed

---

## Phase 3: Validation & Orchestrator Async Refactor

### Overview

Refactor JobValidator and OrchestratorAgent to async. Handle ChromaDB's sync limitation by wrapping get_context() calls in asyncio.to_thread(). Wire POST /validate_jobs and POST /score_jobs endpoints.

### Changes Required

#### 1. Job Validator Async Refactor

**File**: `src/tools/job_validator.py`

**Intent**: Convert `is_job_valid()` method to async, replace requests.get() with httpx, replace time.sleep() with asyncio.sleep().

**Contract**: Method signature changes from:
```python
def is_job_valid(self, job: JobOffer) -> bool
```
to:
```python
async def is_job_valid(self, job: JobOffer) -> bool
```

Key changes (from research):
- Line 53: `response = requests.get(...)` → `async with httpx.AsyncClient() as client: response = await client.get(...)`
- Line 121: `self.checker.invoke(prompt)` → `await self.checker.ainvoke(prompt)`
- Line 127: `time.sleep(backoff)` → `await asyncio.sleep(backoff)` (in retry loop)

#### 2. Validate Jobs Node (Async)

**File**: `src/graph.py`

**Intent**: Convert `validate_and_limit_jobs_node()` from sync to async, awaiting JobValidator calls.

**Contract**: Function signature changes to async:
```python
async def validate_and_limit_jobs_node(state: AgenticHireState) -> dict[str, Any]:
    factory = get_agent_factory()
    valid_jobs = []
    for job in state["found_jobs"]:
        is_valid = await factory.job_validator.is_job_valid(job)  # Now async
        if is_valid:
            valid_jobs.append(job)
    return {"valid_jobs": valid_jobs}
```

#### 3. Orchestrator Agent Async Refactor (with Chroma Wrapping)

**File**: `src/agents/orchestrator.py`

**Intent**: Convert `__call__` method to async, handle Chroma sync limitation.

**Contract**: Method signature changes to async:
```python
async def __call__(self, state: AgenticHireState) -> dict[str, Any]
```

Key changes (from research):
- Line 50: `relevant_cv_parts = self.vector_manager.get_context(...)` → wrap in `asyncio.to_thread()`:

```python
relevant_cv_parts = await asyncio.to_thread(
    self.vector_manager.get_context,
    search_query,
    k=3
)
```

- Line 76: `rating = self.judge.invoke(prompt)` → `await self.judge.ainvoke(prompt)`
- All LLM calls: `.invoke()` → `.ainvoke()`

#### 4. Validate Jobs Endpoint

**File**: `src/api/routes/validation.py` (new file)

**Intent**: Wire POST /validate_jobs endpoint that filters invalid/expired jobs.

**Contract**: Endpoint signature:
```python
@router.post("/validate_jobs")
async def validate_jobs(request: ValidateJobsRequest) -> ValidateJobsResponse:
    factory = get_factory()
    state = {
        "found_jobs": request.jobs,
        "valid_jobs": [],
        "rejected_jobs": [],
        ...
    }
    result = await validate_and_limit_jobs_node(state)
    return ValidateJobsResponse(
        valid_jobs=result["valid_jobs"],
        rejected_jobs=result["rejected_jobs"]
    )
```

#### 5. Score Jobs Endpoint

**File**: `src/api/routes/scoring.py` (new file)

**Intent**: Wire POST /score_jobs endpoint that invokes OrchestratorAgent.

**Contract**: Endpoint signature:
```python
@router.post("/score_jobs")
async def score_jobs(request: ScoreJobsRequest) -> ScoreJobsResponse:
    factory = get_factory()
    state = {
        "valid_jobs": request.jobs,
        "shortlisted_jobs": [],
        ...
    }
    result = await factory.orchestrator(state)
    return ScoreJobsResponse(
        shortlisted_jobs=result.get("shortlisted_jobs", []),
        scores={job.id: job.match_score for job in result.get("shortlisted_jobs", [])}
    )
```

### Success Criteria

#### Automated Verification

- [ ] 3.1 `uv run mypy src/tools/job_validator.py src/agents/orchestrator.py` passes
- [ ] 3.2 `uv run pytest tests/test_validator_async.py tests/test_orchestrator_async.py` passes
- [ ] 3.3 `uv run pytest tests/test_graph.py` (verify async node integration) passes

#### Manual Verification

- [ ] 3.4 POST /validate_jobs with dead links returns valid subset (200 errors filtered)
- [ ] 3.5 POST /score_jobs with valid jobs returns scores (0.0–1.0) per job
- [ ] 3.6 Scores >= 0.6 threshold appear in shortlisted_jobs
- [ ] 3.7 Error response for job with malformed URL is structured JSON

---

## Phase 4: Tailor Agent & Full Endpoint Wiring

### Overview

Refactor TailorAgent to async, wire POST /evaluate_job endpoint, integrate full agent workflow into FastAPI. All agents are now async-capable and callable from HTTP endpoints.

### Changes Required

#### 1. Tailor Agent Async Refactor

**File**: `src/agents/tailor.py`

**Intent**: Convert `__call__` method to async.

**Contract**: Method signature changes to async:
```python
async def __call__(self, state: AgenticHireState) -> dict[str, Any]
```

Key changes (from research):
- Line 63: `response = self.llm.invoke([...])` → `await self.llm.ainvoke([...])`
- All LLM calls: `.invoke()` → `.ainvoke()`
- URL parsing (urllib.parse) stays sync (no I/O)

#### 2. Evaluate Job Endpoint

**File**: `src/api/routes/evaluation.py` (new file)

**Intent**: Wire POST /evaluate_job/{job_id} endpoint that invokes TailorAgent.

**Contract**: Endpoint signature:
```python
@router.post("/evaluate_job/{job_id}")
async def evaluate_job(job_id: str, request: EvaluateJobRequest) -> EvaluateJobResponse:
    factory = get_factory()
    state = {
        "shortlisted_jobs": [request.job],
        "applications": {},
        ...
    }
    result = await factory.tailor(state)
    return EvaluateJobResponse(
        job_id=job_id,
        evaluation=result["applications"].get(job_id, "")
    )
```

#### 3. Integrate Routes into FastAPI App

**File**: `src/api/main.py` (update)

**Intent**: Import and register all route blueprints.

**Contract**: Main app file includes:
```python
from src.api.routes import search, validation, scoring, evaluation

app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(validation.router, prefix="/api", tags=["validation"])
app.include_router(scoring.router, prefix="/api", tags=["scoring"])
app.include_router(evaluation.router, prefix="/api", tags=["evaluation"])
```

All four endpoints now available under /api prefix (or root, per design).

### Success Criteria

#### Automated Verification

- [ ] 4.1 `uv run mypy src/agents/tailor.py src/api/` passes
- [ ] 4.2 `uv run pytest tests/test_tailor_async.py` passes
- [ ] 4.3 `uv run pytest tests/test_api_endpoints.py` (full integration tests) passes
- [ ] 4.4 `uv run black src/api/ --check` passes formatting

#### Manual Verification

- [ ] 4.5 Full workflow: POST /search_jobs → /validate_jobs → /score_jobs → /evaluate_job/{job_id} completes end-to-end
- [ ] 4.6 Evaluation responses include one-sentence summaries per job
- [ ] 4.7 Concurrent multi-request workflow doesn't have race conditions
- [ ] 4.8 All responses are properly formatted JSON (no Python object dumps)

---

## Phase 5: Docker Integration & Testing

### Overview

Update Dockerfile to support FastAPI (uvicorn), add new 'api' service to docker-compose.yml, configure health checks, verify full stack runs locally with one command.

### Changes Required

#### 1. Update Dockerfile

**File**: `Dockerfile`

**Intent**: Add uvicorn, ensure FastAPI code is copied, expose both Streamlit (8501) and FastAPI (8000) ports.

**Contract**: Dockerfile includes:
- `EXPOSE 8000` (FastAPI)
- Copy `src/api/` directory (already covered by `COPY src/ ./src/`)
- Install uvicorn (via pyproject.toml dependency)
- Entrypoint can run either Streamlit or FastAPI depending on CMD

**Changes** (multi-stage build already exists, just update):
- No Streamlit-specific CMD in Dockerfile; Docker Compose specifies CMD per service
- Ensure both ports exposed

#### 2. Update Docker Compose

**File**: `docker-compose.yml`

**Intent**: Add new 'api' service running FastAPI; keep 'app' service (Streamlit).

**Contract**: Compose file includes two services:

```yaml
services:
  app:  # Existing Streamlit (unchanged)
    build: .
    command: streamlit run ui.py --server.port=8501 --server.address=0.0.0.0
    ports:
      - "8501:8501"
    environment:
      AGENTIC_HIRE_OPENROUTER_API_KEY: ${AGENTIC_HIRE_OPENROUTER_API_KEY}
      AGENTIC_HIRE_ORIOSEARCH_BASE_URL: ${AGENTIC_HIRE_ORIOSEARCH_BASE_URL:-http://host.docker.internal:8000}
      AGENTIC_HIRE_LOG_LEVEL: ${AGENTIC_HIRE_LOG_LEVEL:-INFO}
    volumes:
      - ./data/cv:/app/data/cv
      - chroma_db:/app/data/chroma_db
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

  api:  # New FastAPI service
    build: .
    command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    environment:
      AGENTIC_HIRE_OPENROUTER_API_KEY: ${AGENTIC_HIRE_OPENROUTER_API_KEY}
      AGENTIC_HIRE_ORIOSEARCH_BASE_URL: ${AGENTIC_HIRE_ORIOSEARCH_BASE_URL:-http://host.docker.internal:8000}
      AGENTIC_HIRE_LOG_LEVEL: ${AGENTIC_HIRE_LOG_LEVEL:-INFO}
    volumes:
      - ./data/cv:/app/data/cv
      - chroma_db:/app/data/chroma_db
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          memory: 4G
        reservations:
          memory: 2G

volumes:
  chroma_db:
    driver: local
```

#### 3. Dockerfile Health Check Update

**File**: `Dockerfile`

**Intent**: Add health check for FastAPI service (docker-compose already has it, but good to have in Dockerfile too for standalone runs).

**Contract**: Dockerfile HEALTHCHECK command can be generic or per-CMD; for now, keep Streamlit's health check (app service uses it).

#### 4. Environment Variables & .env

**File**: `.env.example` (update)

**Intent**: Document all required and optional environment variables for FastAPI.

**Contract**: .env.example includes all vars that both services need:
```
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-...
AGENTIC_HIRE_ORIOSEARCH_BASE_URL=http://host.docker.internal:8000
AGENTIC_HIRE_LOG_LEVEL=INFO
# ... other existing vars
```

### Success Criteria

#### Automated Verification

- [ ] 5.1 `docker build -t agentic-hire-ai:fastapi .` completes without errors
- [ ] 5.2 `docker-compose config` validates compose file syntax
- [ ] 5.3 `docker-compose up --dry-run` (if supported) shows both services will start

#### Manual Verification

- [ ] 5.4 `docker-compose up` starts without errors
- [ ] 5.5 Both services healthy: `docker-compose ps` shows "Up" for api and app
- [ ] 5.6 `curl http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] 5.7 `curl http://localhost:8501/_stcore/health` returns 200 OK (Streamlit)
- [ ] 5.8 POST http://localhost:8000/search_jobs with sample criteria returns jobs via Docker
- [ ] 5.9 Full workflow (search → validate → score → evaluate) works via Docker endpoints
- [ ] 5.10 Streamlit UI at http://localhost:8501 still loads (no regression)
- [ ] 5.11 Regression test: Sample CV embeddings + scoring match prior CLI/Streamlit output (quality verified)
- [ ] 5.12 Docker logs: both services log startup messages, no errors in logs

---

## Testing Strategy

### Unit Tests

**New test files** to create/update:

- `tests/test_scout_async.py` — Scout agent async behavior, tool invocation
- `tests/test_validator_async.py` — JobValidator async HTTP validation
- `tests/test_orchestrator_async.py` — OrchestratorAgent async, Chroma wrapping
- `tests/test_tailor_async.py` — TailorAgent async behavior
- `tests/test_api_health.py` — Health endpoint responds 200
- `tests/test_api_endpoints.py` — Each POST endpoint with mock agent responses

**Patterns**:
- Mock LLMs and tools with async mocks (AsyncMock from unittest.mock)
- Mock httpx.AsyncClient requests
- Mock Chroma with asyncio.to_thread verification
- Cast state to AgenticHireState for type hints
- Use @pytest.mark.asyncio for async test functions

### Integration Tests

- End-to-end HTTP requests via FastAPI TestClient
- Multiple concurrent requests to verify state isolation
- Full workflow: search → validate → score → evaluate

### Manual Testing

- curl requests to each endpoint
- Postman collection (optional)
- Docker Compose stack integration
- Sample CV regression test (compare Orchestrator and Tailor outputs to prior system)

## Performance Considerations

### Async Benefits
- Event loop handles many concurrent requests without spawning threads
- HTTP I/O (job search, scraping, validation) doesn't block other requests
- Throughput scales better than sync/threading

### Chroma Bottleneck
- `asyncio.to_thread()` offloads Chroma to thread pool
- One request ties up one thread during vector search (acceptable for local MVP)
- Future: Consider migrating Chroma to pgvector (Phase 2) or using async pgvector library

### Expected Latency
- Phase 1 MVP (local Docker Compose): 
  - /health: <10ms
  - /search_jobs: 2–5s (LLM + OrioSearch I/O)
  - /validate_jobs: 1–3s (HTTP checks + LLM validation)
  - /score_jobs: 2–5s (vector search + LLM scoring)
  - /evaluate_job: 1–2s (LLM generation)
- No hard SLA; local developer machine use

## Migration Notes

**No data migration** — F-01 is foundational infrastructure, not a data refactor. 

- Existing ChromaDB persists (Phase 2 will migrate to pgvector)
- Existing CSV files, PDFs remain unchanged
- CLI (main.py) and Streamlit UI (ui.py) coexist with FastAPI during Phase 1
- Users can still run `uv run python main.py` (sync CLI) alongside `uv run uvicorn src.api.main:app`
- Streamlit UI continues to work (unchanged in Phase 1)

## References

- Research: `context/changes/fastapi-scaffold/research.md`
- Roadmap: `context/foundation/roadmap.md` (F-01 section)
- PRD: `context/foundation/prd.md` (Phase 1a, Scope of Change)
- Current agents: `src/agents/` (scout.py, orchestrator.py, tailor.py, agents.py)
- Current tools: `src/tools/` (search.py, scrape.py, job_validator.py, vectordb.py)
- Current state schema: `src/schema/state.py` (AgenticHireState TypedDict)
- Current graph: `src/graph.py` (LangGraph workflow)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: FastAPI Bootstrap

#### Automated

- [x] 1.1 Add FastAPI, httpx, uvicorn dependencies to pyproject.toml
- [x] 1.2 Create src/api/ directory with __init__.py
- [x] 1.3 Create src/api/main.py with FastAPI app, health endpoint
- [x] 1.4 Create src/api/dependencies.py for dependency injection
- [x] 1.5 Create src/api/schemas.py for request/response models
- [x] 1.6 Create src/api/middleware.py for error handling, logging
- [x] 1.7 uv run mypy src/api/ passes strict type checking

#### Manual

- [x] 1.8 GET /health responds with 200 OK

### Phase 2: Scout Agent Async Refactor

#### Automated

- [x] 2.1 Update src/agents/scout.py — __call__ is async, all invoke() → ainvoke()
- [x] 2.2 Update src/tools/search.py — job_search_tool uses httpx.AsyncClient
- [x] 2.3 Update src/tools/scrape.py — scrape_webpage_tool uses httpx.AsyncClient
- [x] 2.4 Create src/api/routes/search.py with POST /search_jobs endpoint
- [x] 2.5 uv run mypy src/agents/scout.py src/tools/ passes
- [x] 2.6 uv run pytest tests/test_scout_async.py passes

#### Manual

- [x] 2.7 POST /search_jobs with sample criteria returns job list

### Phase 3: Validation & Orchestrator Async Refactor

#### Automated

- [x] 3.1 Update src/tools/job_validator.py — is_job_valid async, httpx, asyncio.sleep
- [x] 3.2 Update src/graph.py — validate_and_limit_jobs_node is async
- [x] 3.3 Update src/agents/orchestrator.py — __call__ async, Chroma wrapped in asyncio.to_thread()
- [x] 3.4 Create src/api/routes/validation.py with POST /validate_jobs endpoint
- [x] 3.5 Create src/api/routes/scoring.py with POST /score_jobs endpoint
- [x] 3.6 uv run mypy src/ passes
- [x] 3.7 uv run pytest tests/test_validator_async.py tests/test_orchestrator_async.py passes

#### Manual

- [ ] 3.8 POST /validate_jobs filters dead links correctly
- [ ] 3.9 POST /score_jobs returns match scores (0.0–1.0)

### Phase 4: Tailor Agent & Endpoint Wiring

#### Automated

- [x] 4.1 Update src/agents/tailor.py — __call__ async, invoke → ainvoke
- [x] 4.2 Create src/api/routes/evaluation.py with POST /evaluate_job/{job_id} endpoint
- [x] 4.3 Update src/api/main.py — register all route blueprints
- [x] 4.4 uv run mypy src/ passes
- [x] 4.5 uv run pytest tests/test_tailor_async.py tests/test_api_endpoints.py passes

#### Manual

- [x] 4.6 Full workflow (search → validate → score → evaluate) works end-to-end

### Phase 5: Docker Integration & Testing

#### Automated

- [x] 5.1 Update Dockerfile — ensure FastAPI code copied, uvicorn installed
- [x] 5.2 Update docker-compose.yml — add new 'api' service (port 8000)
- [x] 5.3 docker build succeeds without errors
- [x] 5.4 docker-compose config validates syntax

#### Manual

- [x] 5.5 docker-compose up starts both services (api + app)
- [x] 5.6 curl http://localhost:8000/health returns 200 OK
- [x] 5.7 All POST endpoints respond correctly via Docker
- [x] 5.8 Regression test on sample CV: Agent outputs match prior system quality
