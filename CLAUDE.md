# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

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

For installation, environment setup, and run commands, see @README.md.

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

## Notes for Future Development

- **CV Ingestion is slow** (Vision LLM on all PDF pages): Consider caching more aggressively or lazy-loading embeddings
- **OrioSearch dependency**: Local running instance required; no fallback search provider
- **Rate limiting**: No built-in throttling on API calls; add if scaling to many scout runs
- **Pydantic v2 migration**: Using latest pydantic-settings; be careful with validator decorators if updating

