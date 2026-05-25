# Scout API Endpoint — Plan Brief

> Full plan: `context/changes/scout-api-endpoint/plan.md`

## What & Why

The Scout agent (job discovery) currently has a basic API endpoint (`POST /api/search_jobs`) that lacks user isolation, CV context integration, and database persistence. This plan completes the production implementation: authenticate users → retrieve CV from pgvector → invoke Scout → store jobs in database → return search metadata.

This is critical Phase 1 infrastructure (S-04 on the roadmap) that unblocks downstream endpoints (Validate, Orchestrator, Tailor) and enables the dashboard (user's job history).

## Starting Point

- FastAPI server exists with JWT auth and database infrastructure
- Scout agent works but lacks CV context retrieval and database storage
- CVVectorManager exists (sync, needs async wrapping for FastAPI)
- Job table exists with user_id for isolation
- Current endpoint is stateless (returns results, doesn't persist)

## Desired End State

`POST /api/scout` endpoint that:
- Requires JWT authentication
- Retrieves authenticated user's CV embeddings from pgvector
- Invokes Scout agent with CV context + search criteria
- Stores found jobs in database (scoped to user_id)
- Returns HTTP 200 with search metadata (search_id, found_jobs, criteria, timestamp, count, status)
- Handles errors gracefully (missing CV → search continues with warning; Scout failure → empty results + detail)

## Key Decisions Made

| Decision | Choice | Why | Source |
|---|---|---|---|
| Workflow scope | Scout only (not full graph) | Single responsibility; allows fine-grained endpoint control. Validate/Orchestrate/Tailor are separate endpoints. | User input |
| CV context source | pgvector via CVVectorManager | User-isolated, persistent, matches Phase 1 architecture (FR-009). | User input |
| Database persistence | Store all found_jobs + metadata | Enables job history for dashboard (S-08). Lightweight: criteria + count + timestamp per search. | User input |
| Missing CV handling | Search without context, warn in response | Endpoint always works; quality degrades without CV. Status message informs user. | User input |
| Error handling | Return 200 with empty results + detail | Graceful degradation; avoids 5xx errors. Client sees failure reason in status field. | User input |
| Response format | found_jobs + search metadata | Client can display results and correlate with database record via search_id. | User input |
| Performance model | Async, no timeout limit | Scout takes 30-120s (LLM + scraping). Client waits for complete results. | User input |
| Rate limiting | None (Phase 2) | Simple for Phase 1. Phase 2 adds per-user throttling if needed. | User input |

## Scope

**In scope:**
- User authentication & isolation (JWT + user_id)
- CV context retrieval from pgvector
- Scout agent async integration
- Job persistence to PostgreSQL
- Error handling (missing CV, Scout failure)
- Response with search metadata
- Unit & integration tests

**Out of scope:**
- Full workflow (Validate/Orchestrate/Tailor endpoints separate)
- Streaming responses or partial results
- Search history dashboard (S-08)
- Result pagination
- Rate limiting (Phase 2)
- Background job queuing

## Architecture / Approach

**Request flow:**
1. FastAPI receives `POST /api/scout` with JWT token + SearchJobsRequest (criteria, max_results)
2. `get_current_user` dependency validates JWT → returns User (with user_id)
3. Initialize `AgentFactory(user_id=user.id)` → creates user-scoped vector_manager
4. Async wrapper calls `CVVectorManager.get_context(query=criteria)` via `asyncio.to_thread()` → retrieves semantically relevant CV chunks from pgvector
5. Build state dict with resume_context + target_criteria + max_offers
6. Invoke `await factory.scout(state)` → Scout agent uses tools to find jobs
7. Loop through result["found_jobs"]: set user_id, call `JobRepository.create_or_update()` for each
8. Generate search_id (UUID), capture timestamp
9. Commit to database
10. Return response: { search_id, found_jobs, criteria, count, timestamp, status }

**Error handling:**
- Scout exception → return 200 with empty found_jobs + status message
- Missing CV → get_context() returns "", Scout runs with empty resume_context, status includes warning
- Database failure → propagate exception (global handler returns 500)

## Phases at a Glance

| Phase | What it delivers | Key risk |
|-------|------------------|----------|
| 1. Database Schema | SearchSession table + repository (optional, can defer) | If deferred, skip to Phase 2 |
| 2. Scout Agent Async | CV context retrieval + Scout async wrapping | CVVectorManager sync → async mapping complexity |
| 3. Endpoint Implementation | /api/scout refactored, user isolation, database persistence | Integration of all components; thorough testing needed |
| 4. Testing & Integration | Unit tests, integration tests, backward compatibility | Mocking LLM + database fixtures; ensuring existing workflows still work |

**Prerequisites:** FastAPI scaffold (F-01), PostgreSQL + pgvector (F-02), JWT auth (F-03)
**Estimated effort:** ~2-3 sessions across 4 phases (Phase 1 optional, shortens to 3 phases; Phase 4 is testing/verification)

## Open Risks & Assumptions

- **CVVectorManager sync→async mapping:** Using `asyncio.to_thread()` is safe and standard, but adds one extra thread pool call per request. Not expected to be a bottleneck for this workload.
- **Scout agent response time:** 30-120s is long for HTTP request. Clients should have appropriate timeout (e.g., 3-5 min). If timeout becomes an issue, Phase 2 can add background job infrastructure.
- **Missing CV feedback:** If user has no CV, Scout results may be low quality. Status message warns, but UX should encourage CV upload first (out of scope for this change).
- **Job deduplication:** If same job appears in multiple Scout runs, JobRepository.create_or_update() will overwrite (by job.id + url). This is correct behavior but means latest Scout run's timestamp wins.

## Success Criteria (Summary)

✅ User can call `POST /api/scout` with JWT token + criteria, get back job results in ~1 minute
✅ Found jobs are stored in database, scoped to user_id
✅ Missing CV case: search still works, status includes warning
✅ Error case: Scout failure returns 200 with empty results + detail
✅ Backward compatibility: Streamlit UI and CLI still work
✅ All tests pass (unit + integration)
