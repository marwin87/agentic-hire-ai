# Repository Guidelines

**AgenticHire AI** is an autonomous multi-agent job application system using LangGraph. It discovers jobs, validates them, scores relevance using CV context (RAG), and generates application insights. Python 3.13+, mypy strict mode, pytest.

## Hard Rules

- **Type hints required on all functions and module-level variables.** Mypy is strict (`disallow_untyped_defs = true`, `check_untyped_defs = true`). A function without a return type annotation will fail CI. Use proper type imports from `typing` and `src.schema` (e.g., `Annotated`, `TypedDict`, `JobOffer`).
- **All tests must use `unittest.mock` for external calls** (APIs, external services, file I/O). Do not attempt real network requests or file writes in test mode.
- **Configuration via `@AppConfig` in `src/config/settings.py`, never hardcoded.** Override via `.env` prefixes `AGENTIC_HIRE_*` (e.g., `AGENTIC_HIRE_MAX_VALID_OFFERS=10`).

## Project Structure

- `src/agents/` → Scout, Orchestrator, Tailor (bound via `AgentFactory` singleton).
- `src/tools/` → job_search, scrape_webpage, job_validator, CVVectorManager (RAG).
- `src/schema/state.py` → `AgenticHireState` (TypedDict), `JobOffer` (Pydantic model).
- `tests/` → pytest fixtures and mocked tests mirroring src layout.
- `data/` → PDFs and vector DB storage.
- Entry points: `main.py` (CLI).

Full architecture at @CLAUDE.md.

## Build, Test, and Development Commands

```bash
uv sync                           # Install dependencies
uv run black src/ tests/          # Format code
uv run mypy src/                  # Type check
uv run pytest                     # Run all tests
uv run pytest tests/test_graph.py::test_name -v  # Single test
uv run python main.py             # CLI mode
```

## Coding Style & Naming

- **Format:** Black (line length 88, managed via `black[d]` in dependencies).
- **Type hints:** Mandatory. Use `typing.Annotated` for LangGraph reducer operators (`operator.add`, custom reducers).
- **Naming:** Lowercase snake_case for functions and variables; PascalCase for classes and Pydantic models. Tool names lowercase (e.g., `job_search_tool`).
- **Imports:** Prefer `from typing import` and `from src.schema import` for consistent module structure.

## Testing Guidelines

- **Framework:** pytest with `@pytest.fixture` for state and mock objects (see `tests/test_graph.py:10–32`).
- **Pattern:** Use `@patch()` decorator to mock config, external APIs, and state updates. Cast TypedDict updates with `cast(AgenticHireState, {...})`.
- **Coverage:** No explicit threshold enforced; test coverage for graph edges (rescout logic, validation filters) and tool error cases.
- **Run:** `uv run pytest tests/test_graph.py -v` to run a single file.

## Commit & Deployment

- **Commits:** Lowercase imperative (e.g., `fix mypy errors`, `add scout rescout logic`). See recent `git log`.
- **Config:** All secrets in `.env` (required keys: `AGENTIC_HIRE_OPENROUTER_API_KEY`, `AGENTIC_HIRE_ORIOSEARCH_BASE_URL`). OrioSearch runs locally on port 8000. Full env list at @CLAUDE.md.
