# LangGraph as Master Orchestrator — Plan Brief

> Full plan: `context/changes/graph-workflow-api/plan.md`

## What & Why

Make the LangGraph state machine the primary orchestrator for job search workflows instead of duplicating orchestration logic in the API endpoint layer. Create a new `/api/workflows/search-jobs` endpoint that invokes the graph directly, with comprehensive logging to show orchestration decisions. This aligns the architecture with your vision: graph decides Scout → Validate → Orchestrator → Tailor flow; API simply invokes it.

## Starting Point

The graph already exists (`src/graph.py:80-112`) and works, but:
- It's only used by CLI (main.py) and Streamlit UI, not as the primary API entry point
- `/api/orchestrate` duplicates orchestration logic at the endpoint level instead of calling the graph
- Graph logging is generic; lacks [ORCHESTRATOR] prefix to distinguish orchestration decisions from agent logs
- No structured visibility into how the graph decides to rescout, validate, or proceed

## Desired End State

- **New `/api/workflows/search-jobs` endpoint** accepts criteria or pre-found jobs, invokes `build_graph()`, returns all results with per-job error tracking
- **[ORCHESTRATOR] logging throughout graph** shows all decisions: why rescout was triggered, how many jobs passed validation, when orchestrator scores jobs, tailor evaluation counts
- **Graph is the source of truth** for orchestration; API endpoint is a thin wrapper that handles HTTP concerns (auth, request parsing, response serialization)
- **`/api/orchestrate` deprecated** (can remove in follow-up); workflows endpoint is the new primary path

## Key Decisions Made

| Decision               | Choice                                                    | Why (1 sentence)                                                  | Source |
| --------------------- | --------------------------------------------------------- | ----------------------------------------------------------------- | ------ |
| Graph ownership       | Graph is master orchestrator                              | Centralizes logic; endpoints don't duplicate orchestration        | Plan   |
| New endpoint input    | Criteria + optional pre-found jobs (prefer jobs)          | Matches existing flexibility; client can skip Scout if they want  | Plan   |
| Response mode         | Return atomically once graph completes (no streaming)     | Simpler client contract; all results atomic                       | Plan   |
| Logging detail        | High-level decisions ([ORCHESTRATOR] prefix)             | Clear lineage without noise; matches existing agent prefix style  | Plan   |
| Error handling        | Graceful degradation (200 with per-job errors)           | Partial success is better than nothing; matches Phase 1 pattern   | Plan   |
| Persistence           | Ephemeral (log + return, no database writes)             | Stateless orchestrator; clients can log results if needed         | Plan   |
| Testing strategy      | Mock agents with integration tests (no live API calls)   | Fast, deterministic; tests orchestration logic                    | Plan   |
| /api/orchestrate fate | Deprecate then remove (in follow-up change)              | Single clear path eliminates maintenance burden                   | Plan   |

## Scope

**In scope:**
- Add [ORCHESTRATOR] prefix logging to `src/graph.py` at all decision points (should_rescout, validate, orchestrator, tailor)
- Create new `/api/workflows/search-jobs` endpoint that invokes graph
- Register workflows router in `src/api/main.py`
- Add unit/integration tests for graph flow and endpoint
- Mark `/api/orchestrate` as deprecated (optional removal in follow-up)

**Out of scope:**
- Modifying agent implementations (Scout, Orchestrator, Tailor remain unchanged)
- Streaming results (return atomically)
- Persisting workflow runs to database
- Long-running async job handling
- CV upload changes

## Architecture / Approach

```
┌─────────────────────────────────────┐
│  /api/workflows/search-jobs         │
│  (thin HTTP wrapper)                │
└────────────┬────────────────────────┘
             │ Auth, request parse
             ▼
┌─────────────────────────────────────┐
│  build_graph()                      │  ← Master Orchestrator
│                                     │
│  Scout → Validate → Orchestrator    │
│  ↓ (rescout loop) ↑                 │
│  → Tailor → END                     │
│                                     │
│  [ORCHESTRATOR] logs all decisions  │
└─────────────────────────────────────┘
             │
             ▼ State with results
      Return OrchestrateResponse
     (all_jobs, shortlisted, rejected)
```

**Flow:**
1. Client hits `/api/workflows/search-jobs` with criteria or pre-found jobs
2. Endpoint validates input, extracts user context, retrieves CV context
3. Endpoint invokes `build_graph().ainvoke(state)`
4. Graph orchestrates full flow: Scout → Validate → [rescout loop if needed] → Orchestrator → Tailor
5. Graph logs all decisions with [ORCHESTRATOR] prefix
6. Endpoint extracts results, aggregates into OrchestrateResponse, returns 200
7. If any step fails (except tailor), per-job errors included; workflow continues for other jobs

## Phases at a Glance

| Phase | What it delivers                     | Key risk                                   |
| ----- | ------------------------------------ | ------------------------------------------ |
| 1     | [ORCHESTRATOR] logging in graph      | Log messages don't capture decision nuance |
| 2     | `/api/workflows/search-jobs` endpoint | Endpoint doesn't handle all error cases    |
| 3     | Tests for graph + endpoint           | Test mocks miss real integration issues    |

**Prerequisites:**
- Existing graph compiles and runs (already true)
- OrchestrateResponse schema available (already exists from Phase 1)
- LangGraph 0.1+ installed (already in dependencies)

**Estimated effort:** ~2-3 sessions (Phase 1: ~30min, Phase 2: ~1hr, Phase 3: ~1hr)

## Open Risks & Assumptions

- **Assumption**: Graph state initialization includes all required fields. If a field is missing, `ainvoke()` will fail silently. Mitigation: Tests verify state completeness.
- **Risk**: Tailor timeout handling. If multiple tailor calls timeout, endpoint returns quickly but loses context. Mitigation: Per-job timeout + error tracking.
- **Risk**: Rescout loop infinite loop prevention. `seen_jobs` deduplication must work correctly. Mitigation: Unit tests verify seen_jobs reducer logic.

## Success Criteria (Summary)

- Endpoint invocable via curl with valid JWT; returns OrchestrateResponse with all_jobs, shortlisted_jobs, rejected_jobs
- [ORCHESTRATOR] logs show orchestration decisions (why rescout, validation results, orchestrator invocation)
- Partial failures handled gracefully: one job timeout doesn't block others
- Response structure matches Phase 1 OrchestrateResponse (backward compatible for clients)
