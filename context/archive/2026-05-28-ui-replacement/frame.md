# Frame Brief: Replace Streamlit with Next.js 15 real-time UI

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

There is a 449-line Streamlit frontend (`ui.py`) used for running the
AgenticHire AI pipeline. It is the only user-facing interface. The user wants
to replace it with a modern, visually impressive UI that shows the LangGraph
pipeline progress in real time as animated tiles.

## Initial Framing (preserved)

- **User's stated cause or approach**: Remove Streamlit, introduce a new UI
- **User's proposed direction**: Astro 5 / React 19 / Tailwind 4 / TypeScript stack; show LangGraph thinking as tiles
- **Pre-dispatch narrowing**: Driver is production readiness. Framework resolved to Next.js 15 + React 19 + Tailwind 4 + TypeScript. UI must call the FastAPI backend via HTTP/SSE.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Framework unsuitability** — Streamlit is a prototyping tool; it cannot deliver the visual quality, routing, or UX control required for a production product ← initial framing
2. **Architectural bypass** — `ui.py` imports Python modules directly (`_run_graph`, `build_graph`, `init_db`); it never calls the FastAPI backend that was built across F-01–S-06. The UI and API are fully decoupled by accident.
3. **Missing streaming layer** — The FastAPI workflow endpoint uses `graph.ainvoke()` (waits for full completion); there is no SSE or WebSocket surface. Real-time tile visualization requires `graph.astream()` + a streaming endpoint.
4. **Auth gap** — `ui.py` has no authentication (UUID session, no JWT). The FastAPI backend requires JWT Bearer tokens on all protected routes.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
|---|---|---|
| Framework unsuitability | Streamlit's `st.session_state`, blocking `_run_graph()` call, 0.5s throttled re-render — not suited for animated real-time tiles | STRONG |
| Architectural bypass | `ui.py:15-19` imports `_run_graph`, `build_graph`, `init_db` directly; zero HTTP calls to FastAPI backend | STRONG |
| Missing streaming layer | `src/api/routes/workflows.py:127` uses `graph.ainvoke()`, no `StreamingResponse`, no `.astream()` anywhere in codebase | STRONG |
| Auth gap | `ui.py:37` generates a bare `uuid4()` as user_id; no JWT flow. FastAPI requires `Authorization: Bearer` via `dependencies.py:47` | STRONG |

All four hypotheses are simultaneously true. The initial framing ("replace Streamlit") is correct but underdescribes the scope.

## Narrowing Signals

- `ui.py` calls `_run_graph()` at line 409 — synchronous LangGraph invocation via Python import, not HTTP
- LangGraph's compiled graph supports `.astream()` but it is not wired anywhere in the project
- FastAPI backend has six protected endpoints (auth, scout, validate, workflow, CV upload, job list), all requiring JWT — none currently called by the UI
- `src/graph.py:145` compiles a `StateGraph` with four nodes: scout → validate_jobs → orchestrator → tailor. These map naturally to four tile stages.

## Cross-System Convention

Production frontend/backend separation: frontend talks to API via HTTP. The FastAPI backend was explicitly built as a proper API (JWT auth, REST endpoints, Pydantic schemas) — it was always intended to have a real frontend. The Streamlit UI was a prototyping artifact that outlived its purpose.

SSE streaming for LangGraph: LangGraph's `.astream()` yields node-level events. FastAPI supports `StreamingResponse` with `text/event-stream` media type. This is the standard pattern for streaming LangGraph progress to a browser.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: `ui.py` is a prototype-only Streamlit
> frontend that directly imports Python internals, has no auth, and cannot stream
> real-time events — it must be replaced by a proper Next.js 15 frontend that
> authenticates via JWT and receives live LangGraph node events over SSE from a
> new streaming FastAPI endpoint.

The initial framing was correct. The reframe adds precision: this is **three
parallel deliverables**, not one:
1. A new SSE streaming endpoint on the FastAPI backend (wrap `graph.astream()`)
2. A Next.js 15 + React 19 + Tailwind 4 + TypeScript frontend
3. Deletion of `ui.py` and its direct Python coupling

## Confidence

**HIGH** — all four dimensions have strong evidence. The scope is clear. No ambiguity about what needs to change.

## What Changes for /10x-plan

The plan has two sequential phases:

**Phase 1 — Backend streaming**: Add a new FastAPI endpoint (or modify the existing
`/api/workflows/search-jobs`) to stream LangGraph node events via SSE using
`graph.astream()` and `StreamingResponse`. Each event identifies the current node
(scout / validate / orchestrator / tailor) and carries partial state.

**Phase 2 — Next.js frontend**: Scaffold a Next.js 15 app with:
- JWT login/auth flow (calls existing `/api/auth/login` endpoint)
- CV upload page (calls existing `/api/upload_cv`)
- Workflow dashboard: subscribes to SSE stream, renders each node as an animated
  tile that fills progressively as the pipeline advances
- Results view: shortlisted jobs with match scores from final state
- Delete `ui.py` and all direct Python backend imports

## References

- `ui.py:1-449` — current Streamlit frontend (direct Python import coupling)
- `src/api/routes/workflows.py:25-228` — existing workflow endpoint (non-streaming)
- `src/graph.py:113-145` — LangGraph graph definition (4 nodes, supports `.astream()`)
- `src/api/dependencies.py:47-87` — JWT auth dependency
- `src/api/schemas.py:201-216` — `OrchestrateResponse` (current response shape)
- `src/api/main.py` — FastAPI app mount point
