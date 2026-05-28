# UI Replacement — Plan Brief

> Full plan: `context/changes/ui-replacement/plan.md`
> Frame brief: `context/changes/ui-replacement/frame.md`

## What & Why

`ui.py` is a Streamlit prototype that imports Python internals directly and bypasses the FastAPI
backend entirely — it was never production-ready. It must be replaced by a Next.js 15 frontend
that authenticates via JWT (httpOnly cookies), receives live LangGraph pipeline events over SSE,
and renders each agent as an animated tile showing real-time progress.

## Starting Point

A functional HTML/JS prototype (`ui/auth.html` + `ui/dashboard.html`) already exists and
correctly calls the FastAPI backend with JWT Bearer tokens, CV upload, and blocking job search.
It will be superseded and deleted. The FastAPI workflow endpoint (`/api/workflows/search-jobs`)
uses `graph.ainvoke()` — there is no streaming surface yet, so the SSE endpoint must be built
from scratch.

## Desired End State

The user opens the app, logs in, uploads their CV, enters search criteria, and watches four
animated agent tiles light up in sequence: Scout finds jobs, Validate filters them, Orchestrator
scores them, Tailor writes evaluations. Each tile pulses while active and fills with a result
summary when done. A results panel shows shortlisted jobs after completion. `ui.py` and the
`ui/` folder are gone; FastAPI is API-only.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| UI stack | Next.js 15 + React 19 + Tailwind 4 + TS | Production-ready, simple for a solo non-frontend developer | Frame |
| Frontend location | `frontend/` inside this repo | One repo, shared CI, changes to API contract and UI stay in sync | Plan |
| Docker integration | Add `frontend` service to docker-compose | One `docker compose up` starts everything | Plan |
| SSE event schema | Node name + partial state summary per event | Enough for tile animation without exposing raw internal state | Plan |
| Tile animation | Animated pulse (running) → fill with result summary (complete) | Matches "LLM thinking" goal; agent avatars already exist in `ui/images/` | Plan |
| Token storage | httpOnly cookies via Next.js API route proxy | Protects against XSS token theft; Next.js convention | Plan |
| Error UX | Tile turns red with message; subsequent tiles greyed-out | User sees exactly which agent failed and why | Plan |
| Cleanup scope | Delete `ui.py` + `ui/` + FastAPI FileResponse routes | FastAPI becomes API-only; no dead code | Plan |
| SSE auth path | Next.js API route proxies the SSE stream (adds Bearer header) | `EventSource` can't send custom headers; proxy avoids that constraint | Plan |

## Scope

**In scope:**
- New FastAPI `POST /api/workflows/search-jobs/stream` (SSE, wraps `graph.astream()`)
- Next.js 15 app in `frontend/` — auth, CV upload, workflow dashboard with 4 agent tiles
- httpOnly cookie auth via Next.js API route proxies to FastAPI
- Animated tile states: pending → running → complete → error
- Results panel with shortlisted/rejected jobs
- Docker Compose `frontend` service + CI frontend build gate
- Deletion of `ui.py`, `ui/` folder, FastAPI FileResponse routes

**Out of scope:**
- WebSocket (SSE is sufficient)
- Database schema changes
- Changes to existing `ainvoke` endpoint (kept until Phase 5 deletes it)
- Unit tests for the Next.js frontend (type-check + build are the gates)
- Mobile-specific layout

## Architecture / Approach

```
Browser
  │  POST /api/auth/login        ┐
  │  POST /api/cv/upload         ├── Next.js API routes (httpOnly cookie proxy)
  │  POST /api/workflow/stream   ┘
  │
  ▼
Next.js server (port 3000)
  │  Authorization: Bearer <token from cookie>
  ▼
FastAPI (port 8001)
  │  graph.astream(stream_mode="updates")
  ▼
LangGraph: scout → validate_jobs → orchestrator → tailor
  │  {node_name: update_dict} per node
  ▼
SSE events piped back → Next.js → Browser
```

The browser never directly calls FastAPI. Next.js API routes add the Bearer token from the
httpOnly cookie and proxy all requests — including the SSE stream.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Backend SSE | `POST /api/workflows/search-jobs/stream` streaming node events | `graph.astream()` event shape may differ from docs — verify with real run |
| 2. Next.js + Auth + CV | Runnable Next.js app; login/signup/logout/CV upload working | httpOnly cookie proxy pattern is new to this codebase |
| 3. SSE client + tile model | Hook + types wired to dashboard; placeholder tiles update from stream | ReadableStream parsing edge cases (partial chunks, reconnect) |
| 4. Tile animation + results | Animated agent tiles + results panel — the full visual experience | Avatar images in Docker build (must be in `public/`, copied from `ui/images/`) |
| 5. Docker + CI + cleanup | Full stack via `docker compose up`; legacy code deleted | Next.js Docker image size; CI time; deletions are permanent |

**Prerequisites:** FastAPI backend running locally (Phase 1 depends on it for manual verification)
**Estimated effort:** ~4-5 sessions across 5 phases

## Open Risks & Assumptions

- `graph.astream(stream_mode="updates")` field names match the node names exactly (`scout`,
  `validate_jobs`, `orchestrator`, `tailor`) — assumed from `graph.py:120-123` node registration.
- Tailwind 4 has a different config format than Tailwind 3 — the implementer must use the
  Tailwind 4 setup guide, not the v3 docs.
- The rescout loop (scout → validate_jobs → scout again) may emit multiple `scout` and
  `validate_jobs` events — the tile component must handle node repetition (increment counter,
  not reset to pending).

## Success Criteria (Summary)

- User can complete the full loop — login, upload CV, run search, watch tiles animate, see results — via a browser
- `docker compose up` starts all 3 services; the app is fully functional
- `ui.py` and `ui/` are deleted; `uv run pytest` and `mypy` still pass; CI is green
