# AgenticHire AI

An AI-powered agent system that autonomously searches, validates, evaluates, and tailors job applications using a multi-agent LangGraph architecture combined with RAG and Vision-based CV understanding.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Orchestration** | [LangGraph](https://langchain-ai.github.io/langgraph/) |
| **Backend API** | FastAPI (async, JWT auth) |
| **Frontend** | Next.js 16 (App Router, TypeScript) |
| **Database** | PostgreSQL 17 + pgvector |
| **LLMs / Vision** | OpenRouter (OpenAI, Google, Anthropic models) |
| **RAG** | pgvector embeddings stored in PostgreSQL |
| **PDF Processing** | pdf2image + Vision LLM OCR pipeline |
| **Dependency Management** | uv (Python), npm (Node.js) |
| **Job Discovery** | [OrioSearch](https://www.oriosearch.org/) |

---

## Key Features

### Autonomous Job Discovery
A Scout Agent searches and scrapes job postings from external sources using search and scraping tools, with deduplication across retry cycles.

### Job Validation Layer
Every discovered job is validated before further processing: checks URL reachability, detects expired/closed postings via LLM, and limits results to a configurable target count.

### Controlled Agent Loop
A safe retry mechanism tracks scout run counts and seen job URLs, re-running search if not enough valid jobs are found, stopping after configurable limits.

### Orchestrator (Matchmaker)
Evaluates job suitability using RAG-retrieved CV context, LLM-based scoring (0.0–1.0), and a configurable score threshold for shortlisting.

### Vision-Based CV Understanding
Instead of fragile PDF text extraction, the system uses a Vision LLM pipeline:

```
PDF → Images → Vision LLM → Clean Text → Chunking → Embeddings → PostgreSQL/pgvector
```

### Tailor Agent
Generates a concise final evaluation per shortlisted job using orchestrator reasoning and CV context.

### Next.js Web UI
Full-featured web interface with:
- JWT-based authentication (sign up, login, sign out)
- CV upload with persistence across sessions
- Real-time agent workflow with streaming SSE tiles
- Configurable score threshold per search
- Job history page with per-job delete and clear-all

---

## Architecture

```
╔══════════════════════════════════════════════════════════════╗
║                        ENTRY POINTS                          ║
╠══════════════════════════════════════════════════════════════╣
║   Next.js UI (port 3000)          main.py (CLI)              ║
╚═══════════════════════╦══════════════════════════════════════╝
                        ║  HTTP / SSE
                        ▼
╔══════════════════════════════════════════════════════════════╗
║                    FastAPI (port 8001)                        ║
║  /auth  /cv  /workflows/stream  /api/jobs                    ║
╚═══════════════════════╦══════════════════════════════════════╝
                        ║
                        ▼
╔══════════════════════════════════════════════════════════════╗
║                  LANGGRAPH WORKFLOW                           ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║   ┌─────────────┐     ┌──────────────────┐                  ║
║   │ SCOUT AGENT │────▶│ VALIDATE JOBS    │                  ║
║   │ job search  │     │ URL + LLM check  │                  ║
║   │ scraping    │◀────│ should_rescout() │                  ║
║   └─────────────┘     └────────┬─────────┘                  ║
║                                │ proceed                     ║
║                                ▼                             ║
║                       ┌─────────────────┐                   ║
║                       │  ORCHESTRATOR   │                   ║
║                       │  RAG scoring    │                   ║
║                       │  (0.0 → 1.0)    │                   ║
║                       └────────┬────────┘                   ║
║                                │                             ║
║                                ▼                             ║
║                       ┌─────────────────┐                   ║
║                       │  TAILOR AGENT   │                   ║
║                       │  final eval     │                   ║
║                       └────────┬────────┘                   ║
║                                ▼ END                         ║
╚══════════════════════════════════════════════════════════════╝
                        ║
                        ▼
╔══════════════════════════════════════════════════════════════╗
║                      PERSISTENCE                             ║
╠══════════════════════════════════════════════════════════════╣
║  PostgreSQL 17 + pgvector                                    ║
║  • users, cv_files, jobs tables                              ║
║  • CV embeddings via pgvector                                ║
╚══════════════════════════════════════════════════════════════╝
```

---

## Project Structure

```
agentic-hire-ai/
├── src/
│   ├── agents/
│   │   ├── agents.py           # AgentFactory singleton
│   │   ├── scout.py            # Job discovery agent
│   │   ├── orchestrator.py     # Scoring/matching agent
│   │   └── tailor.py           # Evaluation generation agent
│   ├── tools/
│   │   ├── search.py           # job_search_tool (OrioSearch)
│   │   ├── scrape.py           # scrape_webpage_tool (BeautifulSoup)
│   │   ├── job_validator.py    # HTTP + LLM expiration check
│   │   └── vectordb.py         # CVVectorManager (PDF→embeddings→pgvector)
│   ├── api/
│   │   ├── main.py             # FastAPI app, CORS, lifespan
│   │   ├── schemas.py          # Request/response Pydantic schemas
│   │   ├── dependencies.py     # FastAPI dependency injection
│   │   ├── middleware.py       # Request middleware
│   │   ├── vectordb_async.py   # Async pgvector helpers
│   │   └── routes/
│   │       ├── auth.py         # /signup, /login, /logout
│   │       ├── cv.py           # /api/cv/upload, /api/cv/status
│   │       ├── workflows.py    # /api/workflows/stream (SSE)
│   │       ├── jobs.py         # /api/jobs (list, delete)
│   │       ├── search.py       # /api/search
│   │       └── validation.py   # /api/validation
│   ├── auth/
│   │   └── utils.py            # JWT helpers
│   ├── db/
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   ├── repositories.py     # Async repository pattern
│   │   ├── database.py         # Engine, session factory, init_db/close_db
│   │   ├── config.py           # DB-specific config
│   │   └── __init__.py         # Re-exports init_db, close_db, repositories
│   ├── schema/
│   │   ├── state.py            # AgenticHireState TypedDict + JobOffer model
│   │   └── validation.py       # Shared validation schemas
│   ├── config/
│   │   ├── settings.py         # AppConfig via pydantic-settings
│   │   └── logging.py          # loguru setup
│   ├── utils/
│   │   └── progress.py         # Progress tracking utilities
│   └── graph.py                # LangGraph definition + conditional logic
├── frontend/                   # Next.js 16 App Router
│   ├── app/
│   │   ├── dashboard/          # Main workflow page + jobs history
│   │   ├── login/              # Auth pages
│   │   ├── signup/
│   │   └── api/                # Proxy route handlers
│   ├── components/             # Shared UI components
│   ├── hooks/                  # useWorkflowStream, useCvUpload
│   ├── Dockerfile
│   └── docker-entrypoint.sh
├── alembic/                    # Database migrations
├── alembic.ini
├── main.py                     # CLI entry point
├── Dockerfile                  # API multi-stage build
├── docker-compose.yml          # db + api + frontend services
├── docker-compose.dev.yml      # Local development overrides
├── docker-compose.prod.yml     # Production overrides
├── data/
│   └── cv/                     # PDF resume storage
└── pyproject.toml
```

---

## Getting Started

### Option A — Docker (recommended)

Requires Docker Desktop. All services (PostgreSQL, API, frontend) start together.

```bash
# 1. Copy and fill in required env vars
cp .env.example .env
# Edit .env: set AGENTIC_HIRE_OPENROUTER_API_KEY and AGENTIC_HIRE_JWT_SECRET_KEY

# 2. Start everything
docker compose up

# Frontend:  http://localhost:3000
# API:       http://localhost:8001
```

**Stop:**
```bash
docker compose down
```

**Wipe data (including database):**
```bash
docker compose down -v
```

### Option B — Local development

**Prerequisites:** Python 3.13+, Node.js 20+, PostgreSQL 17 with pgvector, uv

```bash
# Python dependencies
uv sync

# Node dependencies
cd frontend && npm ci && cd ..

# Copy and configure env
cp .env.example .env

# Run database migrations
uv run alembic upgrade head

# Start API (terminal 1)
uv run uvicorn src.api.main:app --reload --port 8001

# Start frontend (terminal 2)
cd frontend && npm run dev
# Open http://localhost:3000
```

### CLI mode

```bash
uv run python main.py
```

---

## Configuration

All settings live in `src/config/settings.py` (class `AppConfig`). Override via `.env` (highest priority) or environment variables prefixed `AGENTIC_HIRE_`.

**Required keys:**

| Variable | Description |
|---|---|
| `AGENTIC_HIRE_OPENROUTER_API_KEY` | API key for LLM access via OpenRouter |
| `AGENTIC_HIRE_JWT_SECRET_KEY` | JWT signing secret (generate: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`) |
| `AGENTIC_HIRE_DATABASE_URL` | PostgreSQL connection string (`postgresql+asyncpg://...`) |

**Optional keys:**

| Variable | Default | Description |
|---|---|---|
| `AGENTIC_HIRE_ORIOSEARCH_BASE_URL` | `http://localhost:8000` | OrioSearch job discovery service |
| `AGENTIC_HIRE_MAX_VALID_OFFERS` | `1` | Target number of jobs per workflow run |
| `AGENTIC_HIRE_MAX_SCOUT_RUNS` | `5` | Maximum rescout attempts |
| `AGENTIC_HIRE_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `ERROR`) |
| `AGENTIC_HIRE_ENVIRONMENT` | `development` | `development` enables auto-reload |

---

## Development

### Run tests
```bash
uv run pytest
uv run pytest tests/test_graph.py -v          # single file
uv run pytest tests/test_graph.py::test_name  # single test
```

### Type check & lint
```bash
uv run mypy src/
uv run black src/ tests/ main.py
cd frontend && npm run type-check
```

### Database migrations
```bash
uv run alembic upgrade head       # apply migrations
uv run alembic revision --autogenerate -m "description"  # create new migration
```

---

## OrioSearch

The Scout Agent requires a locally running [OrioSearch](https://www.oriosearch.org/) instance for job discovery. Start it on port 8000 before running the workflow. When using Docker Compose, the API container reaches it via `host.docker.internal:8000`.

---

## License

MIT License — see [LICENSE](LICENSE) for details.
