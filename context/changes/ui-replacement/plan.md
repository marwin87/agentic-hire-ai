# UI Replacement — Next.js 15 + SSE Streaming Implementation Plan

## Overview

Replace the Streamlit `ui.py` prototype and the vanilla HTML `ui/` prototype with a
production-grade Next.js 15 frontend. The new UI authenticates via JWT (httpOnly cookies),
streams LangGraph pipeline progress over SSE, and visualises each agent as an animated tile.
Delete all legacy UI code when the new frontend ships.

## Current State Analysis

- `ui.py` (449 lines): Streamlit frontend that imports Python internals directly (`_run_graph`,
  `build_graph`, `init_db`). Bypasses FastAPI entirely. Has no auth.
- `ui/auth.html` + `ui/dashboard.html`: Vanilla JS prototype served by FastAPI's `FileResponse`
  routes (`/` and `/dashboard` in `src/api/main.py:108-119`). Calls FastAPI with JWT Bearer
  tokens; CV upload and `ainvoke` job search work. Will be replaced, then deleted.
- `src/api/routes/workflows.py:127`: Uses `graph.ainvoke()` — waits for full pipeline
  completion before returning. No streaming surface exists.
- `src/graph.py:113-145`: LangGraph `StateGraph` with 4 nodes: `scout`, `validate_jobs`,
  `orchestrator`, `tailor`. Supports `.astream(stream_mode="updates")` — yields
  `{node_name: output_dict}` after each node completes.
- `src/api/main.py:60-68`: CORS already allows `http://localhost:3000`.
- `ui/images/`: Contains `scout_avatar.jpg`, `orch_avatar.jpg`, `tailor_avatar.jpg`,
  `cpu_avatar.jpg` — per-agent avatars for tile design.

## Desired End State

A user opens the app, logs in, uploads their CV, enters search criteria, and watches four
animated agent tiles light up in sequence as the LangGraph pipeline runs in real time:
Scout finds jobs, Validate filters them, Orchestrator scores them, Tailor writes evaluations.
Each tile pulses while its agent is working and fills with results when done. A results panel
appears below the tiles when the workflow completes. The Streamlit `ui.py` and the HTML `ui/`
folder are gone; FastAPI is API-only.

### Key Discoveries

- `graph.astream(stream_mode="updates")` yields after each node completes — not mid-node.
  The frontend infers the "running" tile by knowing the graph topology, not from an explicit
  start event.
- `EventSource` (browser SSE API) does not support custom headers, so the SSE endpoint
  cannot be authenticated via the standard `HTTPBearer` dependency. Chosen fix: the Next.js
  server-side API route acts as an authenticated proxy — it reads the httpOnly cookie, adds
  `Authorization: Bearer` to the upstream FastAPI call, and pipes the SSE stream back to the
  browser. The browser targets the Next.js route, not FastAPI directly.
- The existing `POST /api/workflows/search-jobs` (`ainvoke`) must remain untouched —
  do not break the HTML prototype's integration until Phase 5 deletes it.

## What We're NOT Doing

- No WebSocket — SSE (unidirectional server-push) is sufficient for streaming pipeline events.
- No database schema changes — this plan adds no new tables.
- No changes to the LangGraph graph nodes or scoring logic.
- No changes to the existing `ainvoke` endpoint until it is deleted in Phase 5.
- No mobile-specific layout work — responsive but not mobile-first.
- No testing of the Next.js frontend with unit tests — type-checking and build serve as the
  automated verification gate; visual behaviour is manual.
- No internationalization.

## Implementation Approach

**Phase 1** wraps `graph.astream()` in a new FastAPI `StreamingResponse` endpoint without
touching the existing `ainvoke` endpoint. The stream emits one JSON event per node completion
plus a final `workflow_complete` event carrying the full `OrchestrateResponse`.

**Phases 2–4** build the Next.js frontend incrementally: scaffold + auth first, then the SSE
client hook, then the animated tile UI. Each phase leaves a runnable, testable app.

**Phase 5** adds Docker integration, updates CI, and deletes all legacy code.

## Critical Implementation Details

**SSE auth proxy pattern**: The browser calls `GET /api/workflow/stream` on the *Next.js*
server (not FastAPI). The Next.js route handler reads the `access_token` httpOnly cookie,
calls `POST /api/workflows/search-jobs/stream` on FastAPI with `Authorization: Bearer <token>`,
and returns the `ReadableStream` back to the browser via `Response` with
`Content-Type: text/event-stream`. This avoids the `EventSource` header limitation entirely.

**`astream` event shape**: `graph.astream(state, stream_mode="updates")` yields one dict per
node: `{"scout": {<state update>}}`. Each update contains only the fields the node wrote to
state (LangGraph merge semantics). Extract the relevant summary fields from the update before
emitting to SSE — do not forward raw state to the frontend.

**SSE keep-alive**: FastAPI's `StreamingResponse` with an async generator will silently drop
the connection if no event is emitted for ~30 seconds (Uvicorn's idle timeout). Emit a
`:keepalive\n\n` comment every 15 seconds while the graph is running (use `asyncio.sleep` with
a timeout wrapper around the `astream` call if needed).

**Next.js App Router + streaming**: Use `fetch` with `ReadableStream` in the Next.js API route
to proxy the SSE stream. Do not buffer the full response. Set
`headers: {'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}`.

---

## Phase 1: Backend SSE Streaming Endpoint

### Overview

Add a new streaming variant of the workflow endpoint that uses `graph.astream()` and emits
per-node SSE events. The existing `ainvoke` endpoint is untouched.

### Changes Required

#### 1. New SSE event schema

**File**: `src/api/schemas.py`

**Intent**: Define the `WorkflowStreamEvent` Pydantic model that every SSE event serialises to.
Keeps the event shape typed and validated on the Python side.

**Contract**: Add after `OrchestrateResponse`. Fields: `node: str` (node name or `"workflow"`
for the final event), `status: Literal["running", "complete", "error"]`, `data: dict[str, Any]`.
Per-node `data` payloads:
- `scout`: `{"jobs_found": int, "scout_run": int}`
- `validate_jobs`: `{"jobs_valid": int, "jobs_rejected": int}`
- `orchestrator`: `{"jobs_shortlisted": int}`
- `tailor`: `{"evaluations": int}`
- `workflow` (final): the serialised `OrchestrateResponse` dict
- `error`: `{"message": str}`

#### 2. New streaming endpoint

**File**: `src/api/routes/workflows.py`

**Intent**: Add `POST /api/workflows/search-jobs/stream` alongside the existing `ainvoke` route.
Builds the same initial `AgenticHireState` as the existing endpoint, then streams it through
`graph.astream(stream_mode="updates")`, emitting a `WorkflowStreamEvent` JSON payload after
each node and a final `workflow_complete` event.

**Contract**: Route decorator `@router.post("/workflows/search-jobs/stream")` returning
`StreamingResponse`. Auth via `user: User = Depends(get_current_user)` (same as existing).
Accepts `OrchestrateRequest`. Returns `StreamingResponse` with
`media_type="text/event-stream"` and `headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}`.

The inner async generator:
1. Builds `AgenticHireState` identically to the `ainvoke` handler (CV context retrieval,
   factory init, criteria/jobs branching).
2. Calls `graph.astream(state, stream_mode="updates")` in an async for loop.
3. For each `{node_name: update_dict}` yielded, extracts the per-node summary (see schema
   above) and yields `f"data: {event_json}\n\n"`.
4. Accumulates final state across updates to reconstruct an `OrchestrateResponse` after the
   loop exits, then yields a final `workflow_complete` event.
5. On exception, yields an `error` event before re-raising.

#### 3. FastAPI import (no change to main.py needed)

The new route is added to the existing `workflows.py` router which is already registered
in `main.py`. No `main.py` changes required for Phase 1.

### Success Criteria

#### Automated Verification

- `uv run pytest tests/ -v --ignore=tests/integration` passes (no existing tests broken)
- `uv run mypy src/` passes

#### Manual Verification

- `curl -N -X POST http://localhost:8001/api/workflows/search-jobs/stream \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"criteria":"python engineer"}' ` streams SSE events to the terminal
- Events arrive in node order: `scout`, then `validate_jobs`, etc.
- A `workflow` completion event arrives last

**Implementation Note**: After completing this phase and all automated verification passes,
pause here for manual confirmation from the human that the manual testing was successful
before proceeding to the next phase.

---

## Phase 2: Next.js Scaffold + Auth + CV Upload

### Overview

Bootstrap the `frontend/` Next.js 15 app, implement JWT auth via httpOnly cookies through
Next.js API route proxies, and build the CV upload page.

### Changes Required

#### 1. Next.js app bootstrap

**File**: `frontend/` (new directory)

**Intent**: Create a Next.js 15 + React 19 + Tailwind 4 + TypeScript project inside the repo.

**Contract**: Use `create-next-app` with `--app --typescript --tailwind` flags (or equivalent
manual setup). The `frontend/` directory contains `package.json`, `tsconfig.json`,
`tailwind.config.ts`, `next.config.ts`, and `app/` (App Router).

Essential `package.json` dependencies: `next@^15`, `react@^19`, `react-dom@^19`.
Essential devDependencies: `typescript`, `@types/react`, `@types/node`, `tailwindcss@^4`.

`next.config.ts` sets `NEXT_PUBLIC_API_URL` default to `http://localhost:8001` (FastAPI port).
In Docker, this is overridden to `http://api:8000` via environment variable.

#### 2. Auth API routes (Next.js server-side proxies)

**Files**:
- `frontend/app/api/auth/login/route.ts`
- `frontend/app/api/auth/signup/route.ts`
- `frontend/app/api/auth/logout/route.ts`
- `frontend/app/api/auth/refresh/route.ts`

**Intent**: These Next.js route handlers proxy auth requests to FastAPI and set/clear an
httpOnly `access_token` cookie. The browser never sees the token — only the cookie.

**Contract**:
- `POST /api/auth/login` → POST to `{API_URL}/api/auth/login`, on success set
  `Set-Cookie: access_token=<token>; HttpOnly; SameSite=Strict; Path=/`
- `POST /api/auth/signup` → POST to `{API_URL}/api/auth/signup`, same cookie flow
- `POST /api/auth/logout` → clear the `access_token` cookie (Set-Cookie with Max-Age=0)
- `POST /api/auth/refresh` → POST to `{API_URL}/api/auth/refresh` with refresh token from
  body, update the httpOnly cookie

#### 3. Auth middleware (route protection)

**File**: `frontend/middleware.ts`

**Intent**: Protect all routes except `/login` and `/signup`. Redirect unauthenticated
requests to `/login`.

**Contract**: `export const config = { matcher: ["/dashboard/:path*", "/api/workflow/:path*"] }`.
Reads `access_token` cookie from the request; if absent, returns `NextResponse.redirect("/login")`.

#### 4. Login and signup pages

**Files**:
- `frontend/app/login/page.tsx`
- `frontend/app/signup/page.tsx`
- `frontend/app/page.tsx` (redirect: logged-in → `/dashboard`, else → `/login`)

**Intent**: Login form posts to the Next.js `/api/auth/login` proxy; on success redirects to
`/dashboard`. Signup form similarly proxies signup. Password strength hints on signup
(matching existing `auth.html` UX).

**Contract**: Client components (`"use client"`). Forms call `fetch('/api/auth/login', ...)`.
No direct FastAPI calls from the browser on these pages.

#### 5. CV upload page

**File**:
- `frontend/app/dashboard/cv/page.tsx`
- `frontend/app/api/cv/upload/route.ts`

**Intent**: Drag-and-drop PDF upload, progress indicator, success/error feedback.
The Next.js API route reads the `access_token` cookie and calls
`POST {API_URL}/api/upload_cv` with `Authorization: Bearer`.

**Contract**: The browser POSTs `multipart/form-data` to `/api/cv/upload` (Next.js route).
The route handler reads the cookie, forwards the file to FastAPI, returns the
`UploadCVResponse` JSON to the browser.

### Success Criteria

#### Automated Verification

- `cd frontend && npm run build` exits 0
- `cd frontend && npm run type-check` exits 0 (add `"type-check": "tsc --noEmit"` to scripts)

#### Manual Verification

- `http://localhost:3000` redirects to `/login` when not authenticated
- Login with valid credentials redirects to `/dashboard`
- Signup creates a new account
- Logout clears the session and redirects to `/login`
- CV upload accepts a PDF and shows chunk count on success
- Unauthenticated access to `/dashboard` redirects to `/login`

**Implementation Note**: After completing this phase and all automated verification passes,
pause here for manual confirmation from the human that the manual testing was successful
before proceeding to the next phase.

---

## Phase 3: SSE Client Hook + Tile Data Model

### Overview

Build the `useWorkflowStream` React hook and the `WorkflowTileState` type system. Wire the
dashboard page to the hook so tiles render as placeholder cards that update from live stream
data. No animation yet — that comes in Phase 4.

### Changes Required

#### 1. SSE proxy route (Next.js)

**File**: `frontend/app/api/workflow/stream/route.ts`

**Intent**: Server-side proxy that reads the httpOnly `access_token` cookie, POSTs to
`{API_URL}/api/workflows/search-jobs/stream` on FastAPI, and pipes the SSE
`ReadableStream` back to the browser.

**Contract**: Accepts `POST` with `{criteria: string, score_threshold?: number}` body.
Reads `access_token` from cookies. Calls FastAPI with `Authorization: Bearer` + JSON body.
Returns `Response` with `Content-Type: text/event-stream`, `Cache-Control: no-cache`,
`X-Accel-Buffering: no`. Streams the response body directly: `return new Response(upstream.body, ...)`.

#### 2. WorkflowTileState type

**File**: `frontend/lib/workflow-types.ts` (new)

**Intent**: Define the TypeScript types for SSE events and tile state. All stream-related
types live here so the hook and components share one source of truth.

**Contract**:
```typescript
type NodeName = "scout" | "validate_jobs" | "orchestrator" | "tailor";
type TileStatus = "pending" | "running" | "complete" | "error";

interface TileData {
  node: NodeName;
  status: TileStatus;
  summary: Record<string, unknown>;     // node-specific result data
  errorMessage?: string;
}

interface WorkflowState {
  tiles: Record<NodeName, TileData>;
  finalResult: OrchestrateResponse | null;
  error: string | null;
  isStreaming: boolean;
}

// Graph topology: which node becomes "running" after each node completes
const NEXT_NODE: Partial<Record<NodeName, NodeName>> = {
  scout: "validate_jobs",
  validate_jobs: "orchestrator",
  orchestrator: "tailor",
};
```

#### 3. useWorkflowStream hook

**File**: `frontend/hooks/useWorkflowStream.ts` (new)

**Intent**: Encapsulate the SSE lifecycle. The hook manages a `fetch` call (not `EventSource`,
since we use a Next.js proxy route that accepts POST), parses the stream, and maintains
`WorkflowState`. Components subscribe to the state; they never touch fetch or SSE directly.

**Contract**:
```typescript
function useWorkflowStream(): {
  state: WorkflowState;
  startWorkflow: (criteria: string, scoreThreshold?: number) => void;
  abortWorkflow: () => void;
}
```

- `startWorkflow` resets state, opens `POST /api/workflow/stream`, reads the response body
  as a `ReadableStream`, parses `data: {...}` SSE lines via `TextDecoder`.
- On each parsed event: updates the matching tile's status and summary; marks the next tile
  in `NEXT_NODE` as `"running"` while the stream is ongoing.
- On `node: "workflow", status: "complete"`: sets `finalResult`, `isStreaming: false`.
- On `node: "<name>", status: "error"`: sets the tile to error, remaining tiles to pending.
- `abortWorkflow` calls `AbortController.abort()` on the fetch.

#### 4. Dashboard page with placeholder tiles

**File**: `frontend/app/dashboard/page.tsx`

**Intent**: The workflow dashboard. Inputs: search criteria text area + score threshold.
Button triggers `startWorkflow`. Renders 4 `TilePlaceholder` cards laid out in a 2×2 grid
(or horizontal row). Results panel renders below (empty until Phase 4).

**Contract**: Uses `useWorkflowStream()`. Passes each `TileData` to a `TilePlaceholder`
component that shows: node name, status badge, and raw `summary` JSON (temporary debug view,
replaced with styled tile in Phase 4). `isStreaming` disables the start button.

### Success Criteria

#### Automated Verification

- `cd frontend && npm run build` exits 0
- `cd frontend && npm run type-check` exits 0

#### Manual Verification

- Dashboard page loads with 4 placeholder tiles (all "pending")
- Entering criteria and clicking Search triggers the SSE stream
- Tiles update from "pending" → "running" → "complete" as events arrive
- Browser DevTools Network tab shows `text/event-stream` response to `/api/workflow/stream`
- Start button is disabled while streaming
- Stream errors update the tile to error state

**Implementation Note**: After completing this phase and all automated verification passes,
pause here for manual confirmation from the human that the manual testing was successful
before proceeding to the next phase.

---

## Phase 4: Tile Animation + Error States + Results View

### Overview

Replace placeholder tile cards with fully animated `AgentTile` components. Add per-agent
avatar images, animated pulse for running state, smooth fill transition on completion, red
error state, and a results panel that renders the shortlisted jobs after the final event.

### Changes Required

#### 1. Agent tile configuration

**File**: `frontend/lib/agent-config.ts` (new)

**Intent**: Central config mapping each `NodeName` to its display label, description, and
avatar image path. Keeps tile presentation data out of component code.

**Contract**:
```typescript
interface AgentConfig {
  node: NodeName;
  label: string;
  description: string;
  avatarSrc: string;    // path relative to /public/images/
}
```

The four configs: Scout ("Job Discovery"), ValidateJobs ("Validation"), Orchestrator
("Scoring & Matching"), Tailor ("Evaluation"). `avatarSrc` values:
`/images/scout_avatar.jpg`, `/images/cpu_avatar.jpg` (for validate_jobs),
`/images/orch_avatar.jpg`, `/images/tailor_avatar.jpg`.

Copy `ui/images/*.jpg` to `frontend/public/images/` as part of this phase.

#### 2. AgentTile component

**File**: `frontend/components/AgentTile.tsx` (new)

**Intent**: Animated tile component with 4 visual states:
- `pending`: muted/greyed card, avatar faded
- `running`: card has pulsing glow border (Tailwind `animate-pulse`), avatar bright
- `complete`: solid border, avatar bright, summary data visible inside the tile
- `error`: red border + red background tint, error icon, `errorMessage` shown

**Contract**: Props: `config: AgentConfig`, `tile: TileData`. Renders a card with the agent
avatar at the top, label + description, and a status area at the bottom that shows the
`summary` fields in human-readable form per node:
- scout: "Found {jobs_found} jobs (run #{scout_run})"
- validate_jobs: "{jobs_valid} valid, {jobs_rejected} rejected"
- orchestrator: "{jobs_shortlisted} shortlisted"
- tailor: "{evaluations} evaluations generated"

Tailwind classes manage state transitions via conditional `className` logic (no CSS-in-JS).

#### 3. Results panel component

**File**: `frontend/components/ResultsPanel.tsx` (new)

**Intent**: Rendered below the tile grid after `finalResult` is non-null. Shows shortlisted
jobs as cards (title, company, URL link, match score as percentage, analysis, evaluation)
and a count of rejected jobs.

**Contract**: Props: `result: OrchestrateResponse | null`. Returns `null` when result is null.
Shortlisted jobs are rendered as green-accented cards sorted by `match_score` descending.
Rejected jobs shown as a collapsed count ("N jobs below threshold").

#### 4. Dashboard page update

**File**: `frontend/app/dashboard/page.tsx`

**Intent**: Replace `TilePlaceholder` with `AgentTile`. Add the `ResultsPanel` below the
tile grid. Arrange tiles in a responsive 2×2 grid on desktop, single column on mobile.

**Contract**: Grid: `grid grid-cols-1 md:grid-cols-2 gap-6`. `ResultsPanel` renders after
the grid. No other structural changes to the page.

### Success Criteria

#### Automated Verification

- `cd frontend && npm run build` exits 0
- `cd frontend && npm run type-check` exits 0

#### Manual Verification

- Running a search shows animated tile transitions: pending → running (pulse) → complete
- Agent avatars appear in each tile
- Completed tiles show human-readable summaries (job counts, evaluation count)
- Error state: if the search criteria returns 0 jobs, the validate_jobs tile turns red
  with a message
- Results panel appears after the last tile completes, with shortlisted jobs displayed
- Rejected job count shown
- The 4-tile layout is responsive (2×2 on wide, 1 column on narrow)

**Implementation Note**: After completing this phase and all automated verification passes,
pause here for manual confirmation from the human that the manual testing was successful
before proceeding to the next phase.

---

## Phase 5: Docker Integration + CI + Cleanup

### Overview

Add the Next.js frontend as a Docker Compose service, update CI to gate on frontend build,
and delete all legacy UI code. FastAPI becomes API-only.

### Changes Required

#### 1. Frontend Dockerfile

**File**: `frontend/Dockerfile` (new)

**Intent**: Multi-stage build: `builder` stage runs `npm run build`, `runner` stage copies
the `.next/standalone` output for a minimal production image. Uses `node:22-alpine`.

**Contract**: Stage 1 (`builder`): `COPY package*.json ./`, `RUN npm ci`,
`COPY . .`, `RUN npm run build`. Stage 2 (`runner`): copies `.next/standalone` +
`.next/static` + `public/`. Sets `CMD ["node", "server.js"]`. Exposes port 3000.

`next.config.ts` must set `output: "standalone"` to enable the standalone build mode.

#### 2. docker-compose.yml frontend service

**File**: `docker-compose.yml`

**Intent**: Add `frontend` service that builds the Next.js Dockerfile and starts on port 3000.

**Contract**:
```yaml
frontend:
  build:
    context: ./frontend
    dockerfile: Dockerfile
  ports:
    - "3000:3000"
  environment:
    - NEXT_PUBLIC_API_URL=http://api:8000
  depends_on:
    - api
  restart: unless-stopped
```

#### 3. docker-compose.dev.yml frontend override

**File**: `docker-compose.dev.yml`

**Intent**: In dev mode, override the frontend service to run `npm run dev` with a volume
mount for hot reload, instead of building the production image.

**Contract**: Override `frontend` with `command: npm run dev` and volume mount
`./frontend:/app:delegated` (exclude `node_modules` with an anonymous volume).

#### 4. CORS update for Docker network

**File**: `src/api/main.py`

**Intent**: Add `http://frontend:3000` to the allowed origins so the frontend Docker service
can call the API service over the internal Docker network.

**Contract**: Add `"http://frontend:3000"` to `allow_origins` list in the
`CORSMiddleware` block (`main.py:61-68`).

#### 5. CI pipeline update

**File**: `.github/workflows/ci.yml`

**Intent**: Remove `ui.py` from the Black format check. Add a `frontend-check` job that
installs Node, runs `npm ci`, then `npm run type-check` and `npm run build`.

**Contract**: In the `Format check with Black` step, change the command to
`uv run black --check src/ tests/ main.py` (drop `ui.py`). Add a new top-level job:
```yaml
frontend-check:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: '22'
        cache: 'npm'
        cache-dependency-path: frontend/package-lock.json
    - run: cd frontend && npm ci
    - run: cd frontend && npm run type-check
    - run: cd frontend && npm run build
```

#### 6. Delete legacy UI files

**Files to delete**:
- `ui.py` — Streamlit frontend
- `ui/` — entire directory (auth.html, dashboard.html, images/)

**Intent**: Remove all legacy UI code. These files have been superseded by the Next.js app.

**Contract**: `git rm -r ui.py ui/`

#### 7. Remove FastAPI FileResponse routes

**File**: `src/api/main.py`

**Intent**: Delete the `GET /` and `GET /dashboard` routes that served the HTML prototype.
FastAPI now serves only API endpoints.

**Contract**: Remove `app.get("/"): async def root()` and
`app.get("/dashboard"): async def dashboard_page()` and their `Path` / `FileResponse` imports
if no longer used elsewhere.

#### 8. Update CLAUDE.md and AGENTS.md

**Files**: `CLAUDE.md`, `AGENTS.md`

**Intent**: Remove Streamlit references; update the project overview, development setup,
and file structure sections to reflect the Next.js frontend and new `frontend/` directory.

**Contract**: In `CLAUDE.md`:
- Remove "Streamlit UI with real-time agent logging" from the Core Concept section
- Replace `ui.py` Streamlit entry-point section with Next.js startup instructions
  (`cd frontend && npm run dev`)
- Update File Structure Reference to show `frontend/` instead of `ui.py`

In `AGENTS.md`:
- Remove `ui.py` from entry points list
- Add `frontend/` to entry points

### Success Criteria

#### Automated Verification

- `docker compose build` exits 0 (all 3 services: db, api, frontend)
- `docker compose up -d --wait --timeout 120` brings all services to healthy
- `curl -f http://localhost:3000` returns HTTP 200 (Next.js app)
- `curl -f http://localhost:8001/health` returns `{"status":"ok"}`
- `uv run black --check src/ tests/ main.py` exits 0 (ui.py gone)
- `uv run pytest tests/ -v --ignore=tests/integration` exits 0 (no import errors from deleted ui.py)
- `cd frontend && npm run type-check` exits 0
- `cd frontend && npm run build` exits 0
- CI pipeline passes on push

#### Manual Verification

- `docker compose up` starts the full stack; browser at `http://localhost:3000` shows the login page
- Full login → CV upload → job search → tile animation flow works end-to-end via Docker
- `ui.py` is gone; `ui/` directory is gone; FastAPI `/` returns 404 (not found)

**Implementation Note**: After completing this phase and all automated verification passes,
pause here for manual confirmation from the human that the manual testing was successful
before completing the change.

---

## Testing Strategy

### Automated Gates (per phase)

Each phase uses `npm run type-check` + `npm run build` as the frontend gate. These catch
type errors and broken imports before manual testing.

Backend changes in Phase 1 are covered by the existing pytest suite (`uv run pytest`).

### Manual Testing Steps (end-to-end, Phase 4+)

1. Start FastAPI: `uv run uvicorn main:app --reload --port 8001`
2. Start Next.js: `cd frontend && npm run dev`
3. Open `http://localhost:3000` → expect redirect to `/login`
4. Sign up with a new account
5. Log in → expect redirect to `/dashboard`
6. Upload a CV PDF → expect success with chunk count
7. Enter search criteria → click Search
8. Watch tiles animate through the 4 pipeline stages
9. Verify results panel shows after completion
10. Test error path: use invalid/no criteria to trigger an empty-result pipeline

## References

- Frame brief: `context/changes/ui-replacement/frame.md`
- Existing workflow endpoint: `src/api/routes/workflows.py:25-228`
- LangGraph definition: `src/graph.py:113-145`
- JWT auth dependency: `src/api/dependencies.py:47-87`
- Current schemas: `src/api/schemas.py:201-216`
- CORS config: `src/api/main.py:57-68`
- HTML prototype (to be deleted): `ui/auth.html`, `ui/dashboard.html`

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.
> Do not rename step titles.

### Phase 1: Backend SSE Streaming Endpoint

#### Automated

- [x] 1.1 `uv run pytest tests/ -v --ignore=tests/integration` passes
- [x] 1.2 `uv run mypy src/` passes

#### Manual

- [x] 1.3 SSE endpoint streams node events in correct order when curled with a valid token
- [x] 1.4 Final `workflow_complete` event arrives and contains full result

### Phase 2: Next.js Scaffold + Auth + CV Upload

#### Automated

- [x] 2.1 `cd frontend && npm run build` exits 0
- [x] 2.2 `cd frontend && npm run type-check` exits 0

#### Manual

- [x] 2.3 Login redirects to dashboard; unauthenticated access to `/dashboard` redirects to `/login`
- [x] 2.4 Signup creates account; logout clears session
- [x] 2.5 CV upload returns chunk count on success

### Phase 3: SSE Client Hook + Tile Data Model

#### Automated

- [x] 3.1 `cd frontend && npm run build` exits 0
- [x] 3.2 `cd frontend && npm run type-check` exits 0

#### Manual

- [x] 3.3 Dashboard shows conversation feed (all agents visible, "pending" agents hidden until active)
- [x] 3.4 Agent bubbles appear as SSE events arrive: thinking dots → checkmark with summary
- [x] 3.5 Network tab shows `text/event-stream` response to `/api/workflow/stream`

### Phase 4: Tile Animation + Error States + Results View

#### Automated

- [x] 4.1 `cd frontend && npm run build` exits 0
- [x] 4.2 `cd frontend && npm run type-check` exits 0

#### Manual

- [x] 4.3 Running state shows animated pulse; completed state fills tile with result summary
- [x] 4.4 Agent avatars appear in each tile
- [x] 4.5 Error state (red tile + message) triggers on pipeline failure
- [x] 4.6 Results panel shows shortlisted jobs after final event

### Phase 5: Docker Integration + CI + Cleanup

#### Automated

- [x] 5.1 `docker compose build` exits 0
- [x] 5.2 `docker compose up -d --wait` brings all 3 services healthy
- [x] 5.3 `curl -f http://localhost:3000` returns 200
- [x] 5.4 `uv run black --check src/ tests/ main.py` exits 0
- [x] 5.5 `uv run pytest tests/ -v --ignore=tests/integration` exits 0
- [x] 5.6 `cd frontend && npm run type-check` exits 0
- [ ] 5.7 CI pipeline passes

#### Manual

- [ ] 5.8 Full stack via `docker compose up` — login → CV upload → search → tiles all work
- [ ] 5.9 `ui.py` deleted, `ui/` directory deleted, FastAPI `/` returns 404
