# Environment Variables Reference

All variables use the `AGENTIC_HIRE_` prefix (handled by pydantic-settings). Set them in `.env` or export before running Docker Compose.

## Required Variables

These must be set before the app starts. The entrypoint validates them and exits with a clear error if any are missing.

| Variable | Purpose | Example / Generation |
|----------|---------|----------------------|
| `AGENTIC_HIRE_OPENROUTER_API_KEY` | API key for all LLM calls (Scout, Orchestrator, Tailor, Vision) | `sk-or-v1-...` — get at https://openrouter.ai/keys |
| `AGENTIC_HIRE_JWT_SECRET_KEY` | JWT signing secret (HS256) | `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
| `AGENTIC_HIRE_DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://agentic_hire:password@db:5432/agentic_hire` |

## PostgreSQL Compose Variables

Used by the `db` service in docker-compose. Must match the `DATABASE_URL` credentials.

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_USER` | `agentic_hire` | Database user |
| `POSTGRES_PASSWORD` | `dev_password` | Database password |
| `POSTGRES_DB` | `agentic_hire` | Database name |

## Optional Variables — Application Behavior

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_DEBUG_MODE` | `true` | Verbose debug logging and stack traces |
| `AGENTIC_HIRE_MAX_VALID_OFFERS` | `3` | Maximum job offers to process per run |
| `AGENTIC_HIRE_MAX_SCOUT_RUNS` | `3` | Maximum scout/re-scout iterations |
| `AGENTIC_HIRE_SCOUT_MAX_ITERATIONS` | `3` | Max LLM tool-call iterations per scout run |
| `AGENTIC_HIRE_SCOUT_RATE_LIMIT_DELAY` | `0.5` | Seconds between scout tool calls (rate limiting) |
| `AGENTIC_HIRE_INITIAL_PROMPT` | *(see settings.py)* | Job search criteria text |
| `AGENTIC_HIRE_CV_FILE_PATH` | `data/cv/sample_cv.pdf` | Path to candidate CV file |
| `AGENTIC_HIRE_EMBEDDING_DIMENSION` | `1536` | Vector dimension for pgvector embeddings |

## Optional Variables — External Services

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_ORIOSEARCH_BASE_URL` | `http://host.docker.internal:8000` | OrioSearch job discovery service URL |
| `AGENTIC_HIRE_OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |

## Optional Variables — LLM Model Selection

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_SCOUT_MODEL_NAME` | `google/gemini-3-flash-preview` | Model for job discovery |
| `AGENTIC_HIRE_ORCHESTRATOR_MODEL_NAME` | `openai/gpt-4o-mini` | Model for job scoring |
| `AGENTIC_HIRE_TAILOR_MODEL_NAME` | `openai/gpt-4o-mini` | Model for application generation |
| `AGENTIC_HIRE_VISION_MODEL_NAME` | `openai/gpt-4o` | Model for CV PDF parsing |
| `AGENTIC_HIRE_VALIDATOR_MODEL_NAME` | `openai/gpt-4o` | Model for job expiration detection |
| `AGENTIC_HIRE_EMBEDDED_MODEL_NAME` | `text-embedding-3-small` | Embedding model for pgvector |

## Optional Variables — Job Validator

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_VALIDATOR_TIMEOUT` | `10` | HTTP timeout (seconds) for job URL checks |
| `AGENTIC_HIRE_VALIDATOR_CONTENT_MAX_CHARS` | `6000` | Max characters to analyze for expiration detection |
| `AGENTIC_HIRE_VALIDATOR_MAX_RETRIES` | `2` | Max retries for LLM validation calls |
| `AGENTIC_HIRE_VALIDATOR_CACHE_ENABLED` | `true` | Cache job validation results |

## Optional Variables — JWT & Auth

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `AGENTIC_HIRE_JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | Access token lifetime (minutes) — default 24h |
| `AGENTIC_HIRE_JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime (days) |
| `AGENTIC_HIRE_PASSWORD_MIN_LENGTH` | `8` | Minimum password length |
| `AGENTIC_HIRE_PASSWORD_REQUIRE_DIGIT` | `true` | Require at least one digit in passwords |
| `AGENTIC_HIRE_PASSWORD_REQUIRE_UPPERCASE` | `true` | Require at least one uppercase letter |

## Optional Variables — Observability

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENTIC_HIRE_JSON_LOGS` | `false` | Enable JSON structured logging on stderr (for Datadog, Splunk, Loki) |
| `AGENTIC_HIRE_ENVIRONMENT` | `development` | Runtime environment (`development` or `production`) |
| `AGENTIC_HIRE_LOG_LEVEL` | `DEBUG` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Quick Reference: Minimum .env for Local Development

```bash
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-or-v1-...
AGENTIC_HIRE_JWT_SECRET_KEY=<run: python -c 'import secrets; print(secrets.token_urlsafe(32))'>
AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@db:5432/agentic_hire
POSTGRES_USER=agentic_hire
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=agentic_hire
```

## Quick Reference: Additional Variables for Production

```bash
AGENTIC_HIRE_ENVIRONMENT=production
AGENTIC_HIRE_LOG_LEVEL=INFO
AGENTIC_HIRE_DEBUG_MODE=false
AGENTIC_HIRE_JSON_LOGS=true
```

See `.env.example` for a fully annotated template.
