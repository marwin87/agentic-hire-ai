---
project: AgenticHire AI
assessed_at: 2026-05-19T00:00:00Z
agent_readiness: ready
context_type: brownfield
stack_components:
  language: Python 3.13
  framework: LangGraph + Streamlit (current) / FastAPI (Phase 1 planned)
  build_tool: uv
  test_runner: pytest
  package_manager: uv
  ci_provider: null
  deployment_target: null (Docker Compose planned)
gates_passed: 7
gates_failed: 0
---

# Stack Assessment: AgenticHire AI

## Stack Components

**Language**: Python 3.13 with type checking via mypy (v2.1.0+). The project requires Python ≥3.13 and enforces strict type discipline through mypy configuration: `check_untyped_defs = true` and `disallow_untyped_defs = true`.

**Orchestration & Core Framework**: LangGraph for multi-agent workflow definition. Agents are structured as LangGraph nodes with a TypedDict-based state machine. Current UI is Streamlit (single-threaded, local); Phase 1 refactor plans FastAPI backend for async agent execution.

**Data & Validation**: Pydantic v2.13+ for runtime data validation. Used throughout for structured agent outputs (JobOffer models, MatchRating, ExpirationCheck). Pydantic-settings for configuration management with `.env` file support.

**Testing**: pytest v9.0+ with mocked tools (unittest.mock) to avoid real API calls. Test structure in `tests/` mirrors source (test_graph.py, test_utils.py, tools/).

**Package Management**: `uv` (modern Python package manager, replaces pip/poetry). Dependencies locked in `uv.lock`.

**Type Checking**: mypy v2.1+ with strict settings. Configured in `[tool.mypy]` section of pyproject.toml.

**Code Quality**: Black for formatting (installed as `black[d]>=26.3.1` in dependencies). EditorConfig present for cross-editor consistency.

**External Integrations**: Calls via OpenRouter (LLM gateway), OrioSearch API (local job discovery service), Vision LLM for CV parsing. All use configurable base URLs and API keys from `.env`.

**CI/CD**: Not yet configured. Phase 1 will add Docker + docker-compose; GitHub Actions or equivalent recommended for Phase 2+.

**Deployment**: No current deployment configuration. Phase 1 target is Docker Compose for local multi-container orchestration (FastAPI + PostgreSQL + pgvector).

## Quality Gate Assessment

### Gate 1: Typed ✓ PASS

**Evidence**: Python 3.13 with mypy strict mode.

`pyproject.toml` declares:
```toml
[tool.mypy]
python_version = "3.13"
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
disallow_untyped_defs = true
```

**Impact for agents**: Function signatures, state shapes (TypedDict in `src/schema/state.py`), and Pydantic models are all type-annotated. An agent can reason about data flow from the source without execution. The strict mypy rules enforce this discipline across the codebase.

---

### Gate 2: Convention-based ✓ PASS

**Evidence**: LangGraph enforces state machine pattern; CLAUDE.md documents folder structure, naming conventions, and agent patterns; pytest discovery is convention-based.

Folder structure (from CLAUDE.md):
- `src/agents/` — agent implementations (ScoutAgent, OrchestratorAgent, TailorAgent)
- `src/tools/` — LangChain tools (job_search_tool, scrape_webpage_tool, job_validator, CVVectorManager)
- `src/schema/` — TypedDict state definitions and Pydantic models (AgenticHireState, JobOffer)
- `src/config/` — settings.py (AppConfig), logging.py
- `tests/` — mirrors source structure

Naming conventions (from CLAUDE.md):
- Tool functions: snake_case with `_tool` suffix where applicable
- Models: PascalCase (JobOffer, MatchRating, ExpirationCheck)
- State fields: snake_case, annotated with operators (operator.add for lists, custom reducers for deduplication)
- Config: CamelCase class (AppConfig), env var prefix AGENTIC_HIRE_

LangGraph graph definition (src/graph.py) enforces node-based workflow with explicit state transitions.

**Impact for agents**: The combination of framework-level structure (LangGraph nodes, Pydantic models) and documented conventions makes the codebase highly navigable. An agent can predict where new agents go, how tools are registered, and what state schema looks like without extensive exploration.

---

### Gate 3: Popular in training data ✓ PASS

**Evidence**: Within Python ecosystem, all components are mainstream.

- **Python 3.13**: Core language, widely represented in training data
- **LangGraph**: Rapidly becoming standard for agent/agentic workflows (LangChain ecosystem, 2023+)
- **Streamlit**: Dominant framework for ML/data-science UIs; well-represented in training data
- **FastAPI** (planned): Fastest-growing async Python web framework; heavily represented in recent training data
- **Pydantic**: Standard for Python data validation and API contracts
- **pytest**: De facto standard testing framework in Python
- **uv**: Emerging as the modern replacement for pip/poetry; growing in training data

**Per-language-family assessment** (per agent-friendly criteria): All components are either established (pytest, Pydantic, Python) or rapidly-ascending within the Python ecosystem (LangGraph, FastAPI, uv).

**Impact for agents**: The agent has likely internalized Python and LangGraph idioms. Code generation will closely follow examples. API bindings and test patterns will be natural.

---

### Gate 4: Well-documented ✓ PASS

**Evidence**: All core dependencies have current, versioned official documentation.

- **Python**: Official docs + PEPs for language features
- **LangGraph**: LangChain documentation with LangGraph guides (improving rapidly)
- **Streamlit**: Official Streamlit docs, API reference, tutorials
- **FastAPI** (planned): Auto-generated OpenAPI docs, extensive Starlette guide, FastAPI tutorial
- **Pydantic**: Official docs with clear examples for v2
- **pytest**: Official pytest docs, well-indexed Stack Overflow corpus
- **uv**: Official UV GitHub repository with README + examples; pip-compatible API docs
- **CLAUDE.md**: Project-specific 400+ line instruction file documenting architecture, patterns, common tasks, and file structure

**Impact for agents**: An agent encountering unfamiliar code can cross-reference official docs. Project-specific patterns are documented in CLAUDE.md. No confusion from out-of-date or scattered docs.

---

## Gaps & Compensation

### Gap 1: CI/CD not configured

**What failed**: No `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, or equivalent detected.

**Why it matters for agents**: Without CI/CD, an agent cannot verify that changes compile, pass tests, or meet linting standards before suggesting PRs. Phase 1 should add this.

**Compensation strategy**:

Add to `.github/workflows/test.yml` (create if absent):
```yaml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: amannn/action-semantic-pull-request@v5  # Optional: enforce commit conventions
      - run: pip install uv && uv sync
      - run: uv run pytest
      - run: uv run mypy src/ tests/
```

Add to `.github/workflows/lint.yml`:
```yaml
name: Lint

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install uv && uv sync
      - run: uv run black --check src/ tests/ main.py ui.py
```

Add to CLAUDE.md (if not present):
```markdown
## CI/CD

Tests run on every push via GitHub Actions:
- `pytest` runs all tests with mocked APIs
- `mypy` validates strict type checking
- `black` checks code formatting

Before pushing, run locally:
```bash
uv run pytest
uv run mypy src/ tests/
uv run black src/ tests/ main.py ui.py --check
```
```

---

### Gap 2: Deployment configuration not present

**What failed**: No `Dockerfile`, `docker-compose.yml`, `fly.toml`, `vercel.json`, or deployment manifest detected.

**Why it matters for agents**: Without deployment infrastructure-as-code, an agent cannot suggest deploy commands or verify that containerization works. Phase 1 explicitly addresses this (Docker Compose).

**Compensation strategy**:

This gap is **intentional and scoped to Phase 1**. Per the PRD, Phase 1a delivers Docker Compose orchestration. No compensation needed; this is planned work.

When Phase 1 is delivered, add references to CLAUDE.md:
```markdown
## Deployment

Full stack runs locally via Docker Compose:
```bash
docker-compose up
```

Includes:
- FastAPI backend (port 8000)
- PostgreSQL + pgvector (port 5432)
- React frontend (port 3000)

For local development without containers:
```bash
uv sync
uv run fastapi dev src/main.py  # Backend in src/main.py (planned)
npm install && npm run dev     # Frontend (separate project)
```
```

---

## Summary

**Overall verdict: READY**

Your stack is **agent-friendly out of the box**. All four quality gates pass:

- ✓ **Typed**: Strict mypy enforcement throughout
- ✓ **Convention-based**: LangGraph patterns + comprehensive CLAUDE.md documentation
- ✓ **Popular in training data**: Mainstream Python stack with rapidly-ascending LangGraph
- ✓ **Well-documented**: All core dependencies have excellent official docs

**Key strengths:**
1. Strong type discipline (mypy strict mode) makes contracts explicit
2. Comprehensive CLAUDE.md (400+ lines) documents architecture, patterns, and common tasks
3. LangGraph is standard for agent workflows; agent has idioms internalized
4. Pydantic for runtime validation bridges the type/runtime gap cleanly

**Current gaps:**
1. CI/CD workflow not yet configured (compensation: add GitHub Actions for pytest + mypy + black)
2. Deployment config not present (intentional; Phase 1 delivers Docker Compose)

**Next step**: `/10x-health-check` will audit dependencies, security, and test coverage. After that, proceed to Phase 1a (backend scaffold + Docker) with confidence that the stack itself is solid.

---

## Recommended Instruction File Additions

### For CI/CD (add to `.github/workflows/` after Phase 1a setup)

None needed — see Compensation section above.

### For Deployment (add to CLAUDE.md after Phase 1e delivery)

```markdown
## Docker Compose Deployment

The full stack runs locally via Docker Compose:

```bash
docker-compose up
```

Services:
- **FastAPI backend**: http://localhost:8000 (see `src/main.py`)
- **PostgreSQL + pgvector**: localhost:5432 (data in `data/postgres/`)
- **React frontend**: http://localhost:3000 (see `frontend/` directory, separate repo)

Environment variables for services are in `docker-compose.yml`. Override via `.env.docker` or environment at run time.

Database migrations run automatically on startup (Alembic, see `src/migrations/`).

For development without Docker:
```bash
uv sync
uv run fastapi dev src/main.py
npm install && npm run dev  # In frontend/ directory
```
```

### For Phase 1 Architecture (already documented, no changes needed)

Your CLAUDE.md already covers:
- Agent factory pattern for LLM/tool initialization
- State management with TypedDict and annotated operators
- Graph structure with conditional edges
- Tool registration and binding
- RAG-before-scoring pattern

No compensation needed — the documentation is comprehensive.
