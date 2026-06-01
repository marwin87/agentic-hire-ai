# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Project Overview

**AgenticHire AI** is an autonomous multi-agent job application system using LangGraph. It discovers jobs, validates them, scores their relevance to a candidate's CV, and generates tailored application insights. The system combines RAG (Retrieval-Augmented Generation) with Vision-based PDF parsing to understand CVs semantically.

### Core Concept

The workflow follows a LangGraph state machine:
1. **Scout** → searches for jobs via OrioSearch API and scrapes job postings
2. **Validate Jobs** → checks if jobs are active/accessible using HTTP validation and LLM expiration detection
3. **Orchestrator (Matchmaker)** → scores job relevance (0.0-1.0) using CV context retrieved from pgvector
4. **Tailor** → generates final evaluation text per job

The system includes:
- **Vision-based CV parsing**: PDF → Images → Vision LLM → text embeddings → pgvector
- **Semantic job matching**: Uses RAG to retrieve relevant CV sections before scoring
- **Controlled retry loop**: Rescouts if insufficient valid jobs found (respects max_scout_runs limit)

## Development Setup

### Dependencies
- **Orchestration**: LangGraph
- **LLM/Vision**: Calls via OpenRouter (supports OpenAI, Google, Anthropic models)
- **Vector DB**: pgvector (PostgreSQL) with embeddings
- **PDF Processing**: pdf2image + PIL for vision-based extraction
- **Web**: BeautifulSoup (scraping), requests (HTTP)
- **Config**: pydantic-settings with .env file support
- **Logging**: loguru

### Environment Setup
```bash
# Install uv (one-time)
pip install uv

# Sync dependencies (creates .venv automatically)
uv sync

# Verify installation
uv run python main.py --help
```

### Configuration
All settings in `src/config/settings.py` (class `AppConfig`). Override via:
1. `.env` file (highest priority)
2. Environment variables prefixed with `AGENTIC_HIRE_` (e.g., `AGENTIC_HIRE_MAX_VALID_OFFERS=10`)
3. Direct edits to settings.py

**Environment Variables**: Copy `.env.example` to `.env` and populate with your API keys and configuration.

**Required .env keys**:
- `AGENTIC_HIRE_OPENROUTER_API_KEY`: API key for model access
- `AGENTIC_HIRE_ORIOSEARCH_BASE_URL`: Typically `http://localhost:8000` (OrioSearch must run locally)

**Key config fields**:
- `max_valid_offers`: Target number of jobs to process (default: 1)
- `max_scout_runs`: Maximum rescout attempts (default: 5)
- `initial_prompt`: Target criteria for job filtering (free-form text)
- `cv_file_path`: Path to CV PDF (default: `data/cv/sample_cv.pdf`)
- `*_model_name`: Different models per agent (scout uses faster model, tailor uses higher temperature)

## Running the Application

### CLI Mode (main.py)
```bash
uv run python main.py
```
Executes the full workflow and prints results. Ingests CV only on first run (hash-based caching).

## Docker Deployment

Local development uses Docker Compose. See `context/foundation/docker-practices.md` for comprehensive guidance.

```bash
docker-compose up
```

**Files**:
- `Dockerfile` — Multi-stage build (Python 3.13, poppler-utils for PDF parsing)
- `docker-compose.yml` — Single app service with volume mounts
- `.dockerignore` — Build context optimization

**Phase 1 preparation** (FastAPI + PostgreSQL):
When you implement Phase 1, the docker-practices guide includes patterns for multi-service orchestration (FastAPI backend, PostgreSQL, pgvector). The current Dockerfile architecture is forward-compatible with that refactor.

## Testing

### Run All Tests
```bash
uv run pytest
```

### Run Specific Test File
```bash
uv run pytest tests/test_graph.py -v
```

### Run Single Test
```bash
uv run pytest tests/test_graph.py::test_should_rescout_max_runs_reached -v
```

### Test Structure
- `tests/test_graph.py`: LangGraph node logic (conditional edges, job validation)
- `tests/test_utils.py`: Utility functions
- `tests/tools/`: Tool-specific tests

Tests use mocking heavily (`unittest.mock`) to avoid actual API calls.

## Architecture Deep Dive

### State Management (TypedDict Pattern)
**File**: `src/schema/state.py`

The `AgenticHireState` is a TypedDict that flows through all LangGraph nodes. Key fields:
- `found_jobs`: Annotated list appended to by Scout (using `operator.add`)
- `valid_jobs`: Filtered list after validation
- `shortlisted_jobs`: Jobs passing Orchestrator score threshold (≥0.6)
- `rejected_jobs`: Invalid/expired jobs (tracked for deduplication)
- `seen_jobs`: Unique URLs to prevent duplicate processing across rescout cycles (uses custom reducer `deduplicate_seen_jobs`)
- `scout_runs`: Incremented counter to enforce max_scout_runs limit

**Pydantic JobOffer Model**: Structured representation with id, title, company, description, url, salary_range, match_score, analysis.

### LangGraph Workflow (src/graph.py)

**Nodes**:
1. **scout** (ScoutAgent): Binds LLM with `job_search_tool` and `scrape_webpage_tool`. Returns `found_jobs`.
2. **validate_jobs**: Pure function filtering invalid jobs and limiting to `max_offers`. Returns `valid_jobs`, `rejected_jobs`, status.
3. **orchestrator** (OrchestratorAgent): Scores each valid job using RAG-retrieved CV context. Returns `shortlisted_jobs`.
4. **tailor** (TailorAgent): Generates final evaluation text per shortlisted job. Returns `applications` dict.

**Conditional Edge** (`should_rescout`):
- Returns `"rescout"` → loops back to scout
- Returns `"proceed"` → advances to orchestrator
- Returns `"end"` → terminates early (e.g., no jobs ever found)

Logic: rescout if valid_jobs < max_offers AND scout_runs < max_scout_runs AND found_jobs not empty OR scout_runs == 0.

### Agents (src/agents/)

**AgentFactory** (agents.py): Central factory pattern for consistent LLM/tool initialization. All agents share OpenRouter base_url and api_key. Returns singleton-like instances via `get_agent_factory()`.

**ScoutAgent** (scout.py):
- Binds tools to LLM: `job_search_tool` (queries OrioSearch API) + `scrape_webpage_tool` (extracts job text)
- Tracks `seen_jobs` to avoid duplicates on rescout
- System prompt emphasizes target_criteria as primary truth, CV as secondary refinement
- Uses `JobParser` utility to extract structured JobOffer objects from raw LLM responses
- On rescout attempts, appends search variation hint to prompt

**OrchestratorAgent** (orchestrator.py):
- Uses `CVVectorManager.get_context()` to retrieve relevant CV chunks via semantic search (RAG)
- Scores each job using structured LLM output (MatchRating: score + reasoning)
- Only shortlists jobs with score ≥ 0.6
- Stores match_score and analysis reasoning in JobOffer for downstream use

**TailorAgent** (tailor.py):
- Generates single-sentence evaluation per shortlisted job
- Uses orchestrator reasoning + CV context + job description in prompt
- Stores output in `applications` dict keyed by job_id

### Tools (src/tools/)

**job_search_tool** (search.py):
- POST to OrioSearch (expects local running instance at config.oriosearch_base_url)
- Returns raw results as string for LLM parsing
- No filtering; LLM decides what's relevant

**scrape_webpage_tool** (scrape.py):
- BeautifulSoup-based HTML extraction (removes scripts/styles)
- Returns first 10,000 characters to avoid token bloat
- Used by Scout to drill into job portals

**JobValidator** (job_validator.py):
- HTTP GET with User-Agent header (avoids blocking)
- Checks status code ≥400 → invalid
- Uses LLM to detect expiration phrases in page text (language-agnostic)
- Called by `validate_and_limit_jobs_node`

**CVVectorManager** (vectordb.py):
- Manages CV ingestion pipeline: PDF → base64 images → Vision LLM OCR → text → chunking → embeddings → pgvector
- Hash-based caching (only re-ingest if CV file changes)
- `ingest_cv()`: Full pipeline; `get_context(query)`: Semantic search retrieval
- Embeddings persist in PostgreSQL (pgvector)

### Configuration & Logging

**src/config/settings.py**: Pydantic BaseSettings with env file support. All magic numbers/prompts centralized here.

**src/config/logging.py**: loguru setup. Debug mode adds file/function/line info; production is compact.

**src/utils.py**: 
- `JobParser`: LLM-based extraction of raw search results into JobOffer Pydantic models
- `JobOfferList`: Container for structured output

## File Structure Reference

```
agentic-hire-ai/
├── src/
│   ├── agents/
│   │   ├── agents.py           # AgentFactory
│   │   ├── scout.py            # Job discovery agent
│   │   ├── orchestrator.py      # Scoring/matching agent
│   │   └── tailor.py           # Content generation agent
│   ├── tools/
│   │   ├── search.py           # job_search_tool (OrioSearch)
│   │   ├── scrape.py           # scrape_webpage_tool (BeautifulSoup)
│   │   ├── job_validator.py    # HTTP + LLM expiration check
│   │   └── vectordb.py         # CVVectorManager (PDF→embeddings→pgvector)
│   ├── schema/
│   │   └── state.py            # AgenticHireState TypedDict + JobOffer model
│   ├── config/
│   │   ├── settings.py         # AppConfig via pydantic-settings
│   │   └── logging.py          # loguru setup
│   ├── graph.py                # LangGraph definition + conditional logic
│   └── utils.py                # JobParser utility
├── main.py                     # CLI entry point
├── tests/                      # pytest fixtures + mocked tests
├── data/
│   └── cv/                     # PDF resume storage
├── pyproject.toml              # uv dependency declaration
└── uv.lock                     # Locked dependency versions
```

## Key Design Patterns

### Annotated State Fields with Operators
Used to aggregate values across multiple node executions:
```python
found_jobs: Annotated[List[JobOffer], operator.add]  # Appends on each Scout run
rejected_jobs: Annotated[List[JobOffer], operator.add]
seen_jobs: Annotated[List[str], deduplicate_seen_jobs]  # Custom reducer
```

### Factory Pattern for Agent Initialization
`AgentFactory` ensures all agents share consistent LLM configuration and tool bindings. Called via `get_agent_factory()` singleton-like getter.

### Structured Output with Pydantic
Agents use `llm.with_structured_output(Pydantic_Model)` to enforce typed responses. Examples:
- `MatchRating` for orchestrator scoring
- `ExpirationCheck` for job validator
- `JobOfferList` for scout job parsing

### RAG Before Scoring
Orchestrator always calls `CVVectorManager.get_context()` before invoking LLM judgment. This retrieves semantically relevant CV sections, improving accuracy.

### Graceful Retry with State Tracking
Scout rescout loop respects `max_scout_runs` and tracks `seen_jobs` to prevent infinite loops while maximizing coverage.

## Common Development Tasks

### Adding a New Tool
1. Define function with `@tool` decorator in `src/tools/`
2. Bind to agent LLM via `llm.bind_tools([new_tool, ...])`
3. Update Scout or relevant agent to handle tool responses
4. Test with mocked API responses in `tests/tools/`

### Modifying Agent Behavior
Edit prompt strings in agent `__call__` methods (e.g., `scout.py` line 65). Use system + human message pattern with `langchain_core.messages`.

### Changing Model Selection
Update `AppConfig` fields in `src/config/settings.py`:
- Scout uses fast/cheap model (google/gemini-3-flash)
- Orchestrator uses balanced model (openai/gpt-4o-mini)
- Tailor uses higher-temperature model (0.7) for creative output
- Vision uses high-capability model for PDF OCR

### Adding LangFuse Tracing
API keys for LangFuse already in `.env` (LANGFUSE_*). Hook into LangChain callbacks for observability (currently not integrated in code).

## Linting & Code Style

**Black** is installed (via `black[d]` in dependencies). No explicit pre-commit hooks configured, but you can lint manually:
```bash
uv run black src/ tests/ main.py
```

## Git Workflow

**Commit Protocol**: When making code changes, always stage files with `git add` but **do NOT auto-commit**. Instead:

1. Stage changes: `git add <files>`
2. Show the user:
   ```
   Changes are ready to commit:
   Commit message: <proposed-message>
   ```
3. Wait for user approval before running `git commit`

This gives you control over what gets committed and the final commit message. Only commit if you explicitly approve or say "go ahead and commit".

**Rationale**: Auto-committing can bundle unrelated changes or use suboptimal messages. You own the git history.

**Exception**: Skip this if you explicitly say "commit as is" or "go ahead and commit" in your message.

## Notes for Future Development

- **CV Ingestion is slow** (Vision LLM on all PDF pages): Consider caching more aggressively or lazy-loading embeddings
- **OrioSearch dependency**: Local running instance required; no fallback search provider
- **Rate limiting**: No built-in throttling on API calls; add if scaling to many scout runs
- **Pydantic v2 migration**: Using latest pydantic-settings; be careful with validator decorators if updating

<!-- BEGIN @przeprogramowani/10x-cli -->

## 10xDevs AI Toolkit - Module 2, Lesson 5

Scale the single-change cycle into parallel work with **worktrees, goal-directed delegation, and multi-session orchestration**:

```
worktree per change -> /goal or claude -p -> PR -> review -> merge
```

The lesson focus is safe throughput: isolated contexts, choosing the right execution mode, and capping parallelism at review capacity.

### Task Router - Where to start

| Skill | Use it when |
| --- | --- |
| **Code isolation** | |
| `git worktree add` | You need a separate working directory for a parallel change. One change per worktree, one fresh agent context per worktree. |
| **Complex changes** | |
| `/10x-implement <change-id> phase <n>` | The change has multiple phases, needs manual gates, or benefits from interactive decision-making during execution. |
| **Simple changes** | |
| `/goal` | You have a clear, bounded task and want goal-directed delegation. The agent works autonomously toward the stated goal with a stop condition. |
| `claude -p` | You want headless execution for a well-defined task. The Ralph Wiggum loop (run, check, retry) is the universal autonomous pattern. |
| **Multi-session orchestration** | |
| Superset / Conductor / Antigravity / VS Code Agent View | You are running multiple agent sessions in parallel and need visibility, coordination, or session management across them. |

### Parallel work rules

- One change per worktree or isolated workspace. One fresh agent context per change.
- Choose interactive `/10x-implement` for complex changes, `/goal` or `claude -p` for simple ones.
- Parallelism is capped by review capacity. More agents without review means more unreviewed code, not higher throughput.
- The quality pain from faster shipping is intentional — it bridges into Module 3 testing gates.

### Lesson boundaries

- Do not reteach interactive `/10x-implement` or `/10x-impl-review`; those are Lessons 2 and 3.
- Do not introduce testing strategy here. The quality pain is the motivation for Module 3.
- Worktrees are a mechanism for isolation, not the topic of a full git tutorial.

### Paths used by this lesson

- `context/changes/<change-id>/` - active change folder
- `context/changes/<change-id>/plan.md` - implementation input for any execution mode

Skills must not write to `context/archive/`. Archived changes are immutable; if a resolved target path starts with `context/archive/`, abort with: "This change is archived. Open a new change with `/10x-new` instead."

<!-- END @przeprogramowani/10x-cli -->
