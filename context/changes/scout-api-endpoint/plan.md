# Scout API Endpoint — Complete Production Implementation

## Overview

Refactor the Scout API endpoint (`POST /api/scout`) from a stateless proof-of-concept into a production-ready agent endpoint that integrates with the Phase 1 infrastructure. The endpoint will:

- Authenticate users via JWT and enforce user isolation (user_id)
- Retrieve user's CV context from pgvector for semantic job matching
- Invoke the Scout agent asynchronously with proper CV context
- Store discovered jobs in PostgreSQL (scoped per user)
- Return structured response with search metadata and job results

This completes **S-04** from the roadmap and unblocks downstream endpoints (S-05, S-06, S-07).

## Current State Analysis

**What exists today:**
- FastAPI application with JWT authentication (get_current_user dependency)
- Database schema: `users`, `cv_embeddings`, `jobs`, `evaluations` tables
- Repositories for all models (UserRepository, JobRepository, etc.) with async CRUD operations
- Scout agent (ScoutAgent class) that binds tools and invokes LLM
- AgentFactory that can be initialized per user with user_id
- CVVectorManager that retrieves CV embeddings from pgvector (requires async support)
- Existing `/api/search_jobs` endpoint that invokes Scout but lacks:
  - User isolation (no user_id enforcement)
  - CV context retrieval from database
  - Job persistence (doesn't store results)
  - Search session tracking

**Key constraint:** CVVectorManager is currently synchronous; async refactor needed to avoid blocking FastAPI event loop.

## Desired End State

**When complete, the Scout endpoint will:**

1. Accept authenticated requests with job search criteria
2. Retrieve user's CV embeddings from pgvector and generate semantic context
3. Invoke Scout agent with CV context, handling missing CV gracefully
4. Store discovered jobs in `jobs` table, scoped to user_id
5. Return HTTP 200 with found_jobs list + search metadata (search_id, criteria, timestamp, count, status)
6. Handle errors gracefully: return 200 with empty results + detail message (not 5xx)
7. Be fully testable with mocked database and LLM calls

**How to verify:**
- Make authenticated POST /api/scout request with criteria and max_results
- Verify response contains search_id, found_jobs array with title/company/url/description
- Verify found jobs appear in database: `SELECT * FROM jobs WHERE user_id = <uuid>`
- Verify missing CV case: endpoint still returns results with warning status
- Verify error handling: malformed requests return 422, auth failures return 401, Scout errors return 200 with empty list

### Key Discoveries:

- **Database ready:** Job model exists with user_id + url + title + company + description + salary_range fields (no migration needed)
- **Repository ready:** JobRepository.create_or_update() handles upserting jobs; no additional methods needed
- **Auth ready:** get_current_user dependency validates JWT and returns User object with user_id
- **CVVectorManager is synchronous:** Uses `asyncio.Runner()` internally, but the public `get_context()` method is synchronous — must wrap in async context or refactor to true async
- **AgentFactory accepts user_id:** Already structured to initialize per-user; Scout agent can access vector_manager with user context
- **SearchSession tracking optional:** No upstream requirement for persistent search history yet; can defer to Phase 2, but recommend adding lightweight metadata (criteria + count) for audit

## What We're NOT Doing

- **Full workflow integration:** Scout endpoint returns found_jobs only; Validate/Orchestrate/Tailor are separate endpoints (invoked downstream)
- **Streaming responses:** Endpoint waits for Scout to complete and returns full results; no partial/streaming results
- **Result pagination:** For now, return all found_jobs (subject to max_results limit in SearchJobsRequest); pagination deferred to dashboard endpoint (S-08)
- **Search history dashboard:** Storing search metadata for later retrieval (S-08); for now, just return results in-request
- **Concurrent scout runs:** Single endpoint call = single search; no queuing or background job infrastructure yet
- **Rate limiting:** Not implementing request throttling; Phase 2 can add per-user rate limits if needed

## Implementation Approach

### Design pattern: User-scoped factory + repository injection

Each request:
1. Extract authenticated user from JWT (via get_current_user dependency)
2. Initialize AgentFactory with user_id → creates CVVectorManager with user's pgvector embeddings
3. Retrieve user's CV context via vector_manager.get_context(query="job search criteria")
4. Invoke Scout agent with CV context + criteria
5. Persist found jobs to database via JobRepository.create_or_update() (scoped to user_id)
6. Return response with search metadata + found jobs

### Critical Implementation Details

**CVVectorManager async compatibility:**
The existing CVVectorManager.get_context() is synchronous but uses asyncio.Runner() internally. To avoid blocking FastAPI's async event loop:
- Option A (recommended): Wrap existing sync method in `asyncio.to_thread()` at the endpoint level (FastAPI handles thread pool)
- Option B: Refactor CVVectorManager.get_context() to be truly async (more invasive; affects existing Streamlit UI code)
- **Chosen: Option A** — wrapping is less risky; preserves backward compatibility with CLI/UI code

**CV context missing case:**
If user has no CV uploaded (no CVEmbedding rows for user_id):
- CVVectorManager.get_context() returns empty string or default message
- Scout agent still runs with empty resume_context
- Response includes warning status: "CV not uploaded; results based on criteria only"
- Do NOT raise error; allow search to proceed

**Error handling strategy:**
Scout agent can fail due to:
- LLM/OpenRouter API timeout
- OrioSearch service unreachable
- Job scraping failures
- Tool execution errors

On any Scout failure:
- Catch exception, log it
- Return HTTP 200 with empty found_jobs list + status message (e.g., "Search failed: OpenRouter timeout")
- Do NOT return 5xx; client should see graceful degradation

**Response contract:**
```python
{
    "search_id": "uuid-string",           # Unique identifier for this search
    "found_jobs": [                        # List of JobOffers found
        {
            "id": "job-id-1",
            "title": "Senior Python Engineer",
            "company": "TechCorp",
            "url": "https://example.com/job/1",
            "description": "Full description text...",
            "salary_range": "$150k-200k"
        },
        ...
    ],
    "criteria": "Python engineer, remote, SaaS",
    "count": 5,
    "timestamp": "2026-05-25T14:30:00Z",
    "status": "Search complete" | "CV not uploaded; results based on criteria only" | "Search failed: <error message>"
}
```

## Phase 1: Database Schema & Models

### Overview

Add lightweight search session tracking (optional but recommended for audit/dashboard). If search history is not required, this phase can be skipped and jump to Phase 2.

### Changes Required:

#### 1. SearchSession Model (optional, defer if not needed for Phase 1)

**File**: `src/db/models.py`

**Intent**: Add SearchSession table to track job searches per user. This enables job history and audit trails (required for S-08 dashboard). Fields: user_id, criteria, found_count, created_at. Minimal footprint.

**Contract**: Add SQLAlchemy ORM model with columns: id (UUID), user_id (FK users), criteria (Text), found_count (Integer), created_at (DateTime). Index on (user_id, created_at) for efficient history queries.

```python
class SearchSession(Base):
    """Job search sessions, one per user search request."""
    __tablename__ = "search_sessions"
    __table_args__ = (Index("ix_search_sessions_user_id_created_at", "user_id", "created_at"),)
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    criteria = Column(Text, nullable=False)
    found_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
```

#### 2. SearchSessionRepository

**File**: `src/db/repositories.py`

**Intent**: Add CRUD operations for SearchSession: create (log search), get_by_user (history).

**Contract**: Add SearchSessionRepository class with methods:
- `async def create(session: AsyncSession, user_id: UUID, criteria: str, found_count: int) -> SearchSession` — create new search record
- `async def get_by_user(session: AsyncSession, user_id: UUID, limit: int, offset: int) -> List[SearchSession]` — retrieve search history

### Success Criteria:

#### Automated Verification:

- [ ] Migration applies cleanly: `alembic upgrade head`
- [ ] SQLAlchemy models compile without errors: `uv run python -c "from src.db.models import SearchSession; print('OK')"`
- [ ] Type checking passes: `uv run mypy src/db/`
- [ ] Unit tests for SearchSessionRepository pass: `uv run pytest tests/test_repositories.py::test_search_session_crud -v`

#### Manual Verification:

- [ ] Connect to local PostgreSQL; verify `search_sessions` table exists with correct schema
- [ ] Insert a test record manually and retrieve via repository
- [ ] Verify foreign key cascade works (delete user → orphaned search_sessions deleted)

---

## Phase 2: Scout Agent & CVVectorManager Async Integration

### Overview

Refactor Scout agent to work properly with async CV context retrieval. Ensure CVVectorManager's get_context() is wrapped safely to avoid blocking FastAPI's event loop.

### Changes Required:

#### 1. Scout Agent Async Enhancement

**File**: `src/agents/scout.py`

**Intent**: Ensure Scout agent can work within async context of FastAPI. Currently calls CVVectorManager synchronously (fine for CLI, not for async FastAPI). Add optional CV context parameter to Scout.__call__() to decouple from vector_manager direct access.

**Contract**: Modify ScoutAgent.__call__() signature to accept optional `cv_context: str` parameter (in addition to existing state). If CV context is provided, use it directly; if not, use default from state. This allows FastAPI to retrieve CV context asynchronously and pass it in.

```python
async def __call__(self, state: AgenticHireState, cv_context: Optional[str] = None) -> dict[str, Any]:
    """
    Args:
        state: Current graph state
        cv_context: Pre-fetched CV context (from pgvector). If None, Scout uses empty context.
    """
    resume_context = cv_context or state.get("resume_context", "No resume context provided.")
    # ... rest of scout logic unchanged
```

#### 2. CVVectorManager Async Wrapper

**File**: `src/api/dependencies.py` or new file `src/api/vectordb_async.py`

**Intent**: Create async wrapper function for CVVectorManager.get_context() to be called from FastAPI routes. Wraps synchronous method in `asyncio.to_thread()` so it doesn't block the event loop.

**Contract**: Add async function:

```python
async def get_cv_context_async(vector_manager: CVVectorManager, query: str = "job matching criteria") -> str:
    """Retrieve CV context asynchronously to avoid blocking FastAPI event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, vector_manager.get_context, query)
```

### Success Criteria:

#### Automated Verification:

- [ ] Type checking passes: `uv run mypy src/agents/scout.py src/api/`
- [ ] Scout agent tests pass: `uv run pytest tests/test_agents/test_scout.py -v`
- [ ] No blocking detected: `uv run python -m asyncio -c "import asyncio; from src.api.vectordb_async import get_cv_context_async; asyncio.run(...)" (manual smoke test)`

#### Manual Verification:

- [ ] Run FastAPI server locally; invoke Scout endpoint, verify it doesn't freeze/hang
- [ ] Monitor event loop: no warnings about blocking calls

---

## Phase 3: Scout API Endpoint Implementation

### Overview

Refactor `/api/search_jobs` endpoint to integrate user authentication, pgvector CV context, database persistence, and proper error handling.

### Changes Required:

#### 1. Refactor `/api/scout` Route Handler

**File**: `src/api/routes/search.py`

**Intent**: Rewrite the POST /search_jobs endpoint to:
- Accept SearchJobsRequest (criteria, max_results)
- Validate authenticated user via get_current_user dependency
- Initialize AgentFactory with user_id
- Retrieve CV context from pgvector asynchronously
- Invoke Scout agent
- Store found jobs in database
- Return structured response with search metadata

**Contract**: Endpoint signature:

```python
@router.post("/scout")
async def scout_search(
    request: SearchJobsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Search for jobs using Scout agent with user's CV context.
    
    - Requires JWT authentication
    - Retrieves CV from pgvector (user_id scoped)
    - Stores found jobs in database (user_id scoped)
    - Returns search metadata + found_jobs
    """
```

**Implementation steps:**
1. Extract user_id from authenticated User object
2. Initialize AgentFactory(user_id=user.id)
3. Retrieve CV context: `cv_context = await get_cv_context_async(factory.vector_manager, request.criteria)`
4. Build state dict with resume_context=cv_context, target_criteria=request.criteria, max_offers=request.max_results
5. Invoke: `result = await factory.scout(state)` (Scout agent must be awaitable)
6. Loop through result["found_jobs"]: for each job, set job.user_id = user.id, then call JobRepository.create_or_update(session, job)
7. Generate search_id (UUID), capture timestamp
8. Commit session: await session.commit()
9. Return response dict with search_id, found_jobs, criteria, count, timestamp, status

**Error handling:**
- If Scout raises exception: catch, log, return 200 with empty found_jobs + status = "Search failed: {error}"
- If CV context retrieval fails: log warning, set cv_context = "", continue (warn in status)
- If database commit fails: let exception bubble (will be caught by global handler, return 500)

#### 2. Update SearchJobsRequest Schema (if needed)

**File**: `src/api/schemas.py`

**Intent**: Verify SearchJobsRequest has correct fields. May need to add max_results default or field descriptions.

**Contract**: Ensure SearchJobsRequest has:
- `criteria: str` — job search query
- `max_results: Optional[int] = 10` — default 10, max 50

#### 3. Update Response Schema

**File**: `src/api/schemas.py`

**Intent**: Add ScoutSearchResponse schema for structured response validation.

**Contract**: Add Pydantic model:

```python
class JobOfferResponse(BaseModel):
    """Job offer in scout response."""
    id: str
    title: str
    company: str
    url: str
    description: Optional[str] = None
    salary_range: Optional[str] = None

class ScoutSearchResponse(BaseModel):
    """Response from POST /scout endpoint."""
    search_id: str
    found_jobs: List[JobOfferResponse]
    criteria: str
    count: int
    timestamp: str  # ISO 8601
    status: str
```

### Success Criteria:

#### Automated Verification:

- [ ] Route imports without errors: `uv run python -c "from src.api.routes.search import router; print('OK')"`
- [ ] Type checking passes: `uv run mypy src/api/routes/search.py`
- [ ] Unit tests pass: `uv run pytest tests/test_api_endpoints.py::test_scout_endpoint -v`
- [ ] Database operations tested: jobs created with correct user_id

#### Manual Verification:

- [ ] Authenticate and call POST /scout with criteria + max_results
- [ ] Verify response includes search_id, found_jobs, criteria, count, timestamp, status
- [ ] Verify jobs stored in database: `SELECT * FROM jobs WHERE user_id = <user-uuid> ORDER BY discovered_at DESC LIMIT 5`
- [ ] Verify job fields match response (title, company, url, description, salary_range)
- [ ] Test CV missing case: upload user without CV, call endpoint, verify status includes "CV not uploaded"
- [ ] Test error gracefully: simulate Scout failure, verify endpoint returns 200 with empty list + error detail

---

## Phase 4: Testing & Integration

### Overview

Write comprehensive tests for endpoint, repository, and Scout agent integration. Ensure all code paths tested (happy path, missing CV, errors).

### Changes Required:

#### 1. Unit Tests for SearchSessionRepository (if Phase 1 completed)

**File**: `tests/test_repositories.py` (add to existing test_repositories.py)

**Intent**: Test CRUD operations for SearchSession.

**Contract**: Add test functions:
- `test_search_session_create` — create and verify
- `test_search_session_get_by_user` — retrieve with pagination
- `test_search_session_cascade_delete` — delete user → orphaned sessions deleted

#### 2. Integration Tests for Scout Endpoint

**File**: `tests/test_api_endpoints.py` (extend existing file)

**Intent**: Test full endpoint flow with mocked LLM, database, and pgvector.

**Contract**: Add test functions:

```python
@patch("src.api.routes.search.get_agent_factory")
@patch("src.api.routes.search.get_cv_context_async")
def test_scout_endpoint_authenticated(mock_cv_context, mock_factory, client, db_session):
    """Test POST /scout with valid auth, found jobs, and database persistence."""
    # Setup mocks
    # Make request with Bearer token
    # Verify response has search_id, found_jobs, count
    # Verify jobs written to database with user_id

@patch("src.api.routes.search.get_agent_factory")
def test_scout_endpoint_missing_cv(mock_factory, client, db_session):
    """Test POST /scout without CV uploaded."""
    # Setup: user has no CV
    # Verify status includes "CV not uploaded"

@patch("src.api.routes.search.get_agent_factory")
def test_scout_endpoint_scout_fails(mock_factory, client, db_session):
    """Test error handling when Scout agent raises exception."""
    # Setup: mock Scout to raise error
    # Verify response is 200 with empty found_jobs + error detail

@patch("src.api.routes.search.get_current_user")
def test_scout_endpoint_unauthenticated(mock_auth, client):
    """Test POST /scout without JWT returns 401."""
    # No token or invalid token
    # Verify 401 response
```

#### 3. End-to-End Test (optional, Phase 2+)

**File**: `tests/test_e2e_scout.py`

**Intent**: Full flow test with real database, mocked LLM. Create user → upload CV → call Scout endpoint.

**Contract**: Single test that:
1. Signup user
2. Upload CV (mocked Vision LLM)
3. Call POST /scout endpoint
4. Verify response and database state

### Success Criteria:

#### Automated Verification:

- [ ] All new tests pass: `uv run pytest tests/test_api_endpoints.py::test_scout_* -v`
- [ ] Existing tests still pass: `uv run pytest tests/ -v`
- [ ] Coverage for scout.py logic: `uv run pytest tests/ --cov=src.api.routes.search --cov-report=term-missing`
- [ ] Type checking passes: `uv run mypy tests/`
- [ ] Linting passes: `uv run black --check tests/ src/api/routes/search.py`

#### Manual Verification:

- [ ] Run Streamlit UI locally; existing workflows still work (backward compatibility)
- [ ] Run CLI: `uv run python main.py` still produces results
- [ ] Start FastAPI: `uv run python -m uvicorn src.api.main:app --reload`
  - [ ] Signup at /auth (or use existing user)
  - [ ] Call POST /scout with valid JWT
  - [ ] Verify found jobs appear on dashboard (S-08 future)

---

## Testing Strategy

### Unit Tests:

- Mock AgentFactory, CVVectorManager, Scout agent
- Test endpoint request validation (SearchJobsRequest)
- Test response serialization (ScoutSearchResponse)
- Test database operations (JobRepository.create_or_update)
- Test edge cases: missing CV, empty results, malformed criteria

### Integration Tests:

- Use TestClient from FastAPI
- Mock LLM calls but use real database fixtures (async fixtures in conftest.py)
- Test full request/response cycle
- Verify jobs written to database with user_id isolation
- Test error paths: 401 (auth), 422 (bad request), 200 with error detail

### Manual Testing Steps:

1. Start FastAPI server: `uv run uvicorn src.api.main:app --reload`
2. Authenticate (signup or login) to get JWT token
3. Make request: `curl -H "Authorization: Bearer <token>" -X POST http://localhost:8000/api/scout -d '{"criteria": "Python engineer", "max_results": 5}'`
4. Verify response includes search_id, found_jobs (5 or fewer), criteria, count, timestamp, status
5. Query database: `SELECT * FROM jobs WHERE user_id = '<uuid>' ORDER BY discovered_at DESC LIMIT 5`
6. Test missing CV: delete user's CVEmbedding rows, re-run step 3, verify status includes warning
7. Test error: mock Scout to fail, verify response is 200 with empty list

## Performance Considerations

**Response time:** Endpoint will take 30-120 seconds (Scout agent + LLM + web scraping). This is expected and acceptable for a job search workflow. Client should not set aggressive timeouts.

**Database writes:** Each found job creates one Job row (or updates if duplicate URL). For typical searches (5-10 jobs), minimal overhead.

**Memory:** Scout agent processes one job at a time; no batching of large lists in memory.

**Concurrency:** FastAPI with default worker count handles multiple concurrent searches (one per user context). No connection pooling concerns for this scale.

## Migration Notes

No database schema migration required if SearchSession model is deferred (Phase 2). If Phase 1 includes SearchSession:
- Run Alembic: `alembic revision --autogenerate -m "Add SearchSession table"`
- Run migrations: `alembic upgrade head`

## References

- CVVectorManager implementation: `src/tools/vectordb.py`
- ScoutAgent implementation: `src/agents/scout.py`
- FastAPI dependencies: `src/api/dependencies.py`
- Job model: `src/db/models.py:Job`
- Existing search endpoint: `src/api/routes/search.py` (to be refactored)
- Authentication: `src/auth.py` (JWT decode logic)

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Do not rename step titles; append ` — <commit sha>` when a step lands.

### Phase 1: Database Schema & Models

#### Automated

- [x] 1.1 Migration applies cleanly: alembic upgrade head — 14cc797
- [x] 1.2 SQLAlchemy models compile without errors — 14cc797
- [x] 1.3 Type checking passes: mypy src/db/ — 14cc797

#### Manual

- [x] 1.4 PostgreSQL table exists with correct schema — 14cc797
- [x] 1.5 Test record insert and retrieve via repository — 14cc797
- [x] 1.6 Foreign key cascade verified — 14cc797

### Phase 2: Scout Agent & CVVectorManager Async Integration

#### Automated

- [x] 2.1 Type checking passes: mypy src/agents/ src/api/ — dd8aeea
- [x] 2.2 Scout agent tests pass — dd8aeea
- [x] 2.3 No event loop blocking detected — dd8aeea

#### Manual

- [x] 2.4 FastAPI server runs without freezing — dd8aeea
- [x] 2.5 Scout endpoint responds within expected timeout — dd8aeea

### Phase 3: Scout API Endpoint Implementation

#### Automated

- [ ] 3.1 Route handler imports without errors
- [ ] 3.2 Type checking passes
- [ ] 3.3 Unit tests pass (mock LLM, database)
- [ ] 3.4 Database operations tested

#### Manual

- [ ] 3.5 Authenticated call to POST /scout returns 200
- [ ] 3.6 Response includes search_id, found_jobs, criteria, count, timestamp, status
- [ ] 3.7 Jobs stored in database with correct user_id
- [ ] 3.8 Missing CV case: status includes "CV not uploaded"
- [ ] 3.9 Error case: Scout failure returns 200 with empty list + error detail
- [ ] 3.10 Unauthenticated request returns 401

### Phase 4: Testing & Integration

#### Automated

- [ ] 4.1 All new tests pass
- [ ] 4.2 Existing tests still pass
- [ ] 4.3 Coverage for scout endpoint ≥ 80%
- [ ] 4.4 Linting passes

#### Manual

- [ ] 4.5 Streamlit UI still works (backward compatibility)
- [ ] 4.6 CLI (main.py) still works
- [ ] 4.7 End-to-end: signup → CV upload → scout → verify results
- [ ] 4.8 FastAPI OpenAPI docs show /scout endpoint (auto-generated)
