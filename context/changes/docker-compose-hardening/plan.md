# Docker Compose Hardening Implementation Plan

## Overview

F-05 hardens the Docker Compose setup from MVP-safe (6/10 production-readiness) to production-ready (9/10) by addressing operational and security gaps discovered in Phase 1. The plan delivers Tier 1 (critical safety: log rotation, CPU limits, secrets validation, graceful shutdown testing) and Tier 2 (operational polish: structured logging, multi-env support, ChromaDB cleanup) across 5 phases, executable within 1-2 weeks post-Phase-1 release.

## Current State Analysis

The Phase 1 Docker setup includes strong foundational patterns:
- Multi-stage Dockerfile with 60% size optimization (Dockerfile:1-63)
- Health checks on db and api services (docker-compose.yml:17-78)
- Memory limits and reservations (docker-compose.yml:81-86)
- Named volumes for data persistence (docker-compose.yml:92-98)
- Entrypoint orchestration with db wait, migrations, service checks (docker-entrypoint.sh:6-62)
- Environment configuration via pydantic-settings with AGENTIC_HIRE_ prefix (src/config/settings.py:13-19)

**Critical gaps** blocking production deployment:
1. **Log rotation missing** — unbounded log growth; disk fills on 24h+ containers
2. **CPU limits not configured** — runaway agents (Vision LLM) can saturate all host cores
3. **No environment variable pre-validation** — bad config causes 5+ minute health check timeout instead of fast failure
4. **pgAdmin exposed on host** — unnecessary security risk on ports 5432, 5050
5. **Secrets with insecure defaults** — `POSTGRES_PASSWORD` and `AGENTIC_HIRE_JWT_SECRET_KEY` default to dev values (anti-pattern)
6. **Graceful shutdown untested** — signal handling is implicit (uvicorn default); edge cases around in-flight transactions unknown
7. **ChromaDB volume orphaned** — deprecated but still in compose; confusion about pgvector vs. ChromaDB authority
8. **Single compose file** — dev-specific bind mounts and debug logging live in production compose

### Key Discoveries:

- **loguru configuration** (src/config/logging.py:5-24): Currently stdout-only, plain text format. No file sinks, no rotation, no structured format. Production format is `{time} | {level} | {message}` (line 21).
- **pydantic-settings pattern** (src/config/settings.py:7-111): AppConfig uses `...` Ellipsis to indicate required fields (e.g., jwt_secret_key:str = Field(...) at line 91); environment variables are loaded with AGENTIC_HIRE_ prefix (line 15); no custom validators currently in use.
- **Entrypoint validation pattern** (docker-entrypoint.sh:2-31): Uses `set -e` for immediate exit on error; 30-attempt polling with 1-second intervals for DB connectivity; exits with code 1 on timeout. No pre-validation of secrets before uvicorn starts — this is the key gap.
- **Docker override pattern**: docker-compose supports `docker-compose -f base.yml -f override.yml` to merge configurations; production overrides can remove services (pgAdmin), tighten limits, and disable bind mounts without duplicating core service definitions.
- **Signal handling** (docker-entrypoint.sh:62): Uses `exec uvicorn ...` to replace shell process, ensuring SIGTERM propagation to uvicorn; but graceful shutdown behavior (draining in-flight requests) is untested.

## Desired End State

After F-05 completes:

1. **Operational safety**: Disk space protected (log rotation), agents capped (CPU limits), fast failure on bad config (pre-startup validation)
2. **Security hardened**: No unnecessary ports exposed (pgAdmin removed), secrets validated at startup, multi-environment separation (dev/prod compose files)
3. **Observability ready**: JSON structured logging configured (ready for Phase 2 log aggregation), graceful shutdown tested in CI
4. **Data safety**: ChromaDB deprecation path clear (removed from compose, migration documented), no orphaned volumes
5. **Production verified**: Docker Compose passes health checks on startup, graceful shutdown tested, startup order validated in CI

### Verification Checklist:

- ✓ Docker logs rotate without manual intervention (100MB chunks, max 10 files)
- ✓ API and DB services have CPU limits; agents can't saturate host
- ✓ Missing secrets caught at startup with clear error (< 1s failure)
- ✓ pgAdmin not in production compose; dev/prod configs are distinct
- ✓ ChromaDB volume removed; MIGRATION.md provides upgrade path
- ✓ `docker-compose kill -s SIGTERM` exits cleanly; no zombie processes
- ✓ `docker-compose up --wait` passes in CI; startup order verified
- ✓ Loguru JSON format configured; Phase 2 aggregation hooks in place

## What We're NOT Doing

- **Secret rotation automation** — Deferred to Phase 2 (HashiCorp Vault, AWS Secrets Manager)
- **Observability integration** — Phase 2: Datadog, Splunk, or Loki hookup
- **Kubernetes or multi-region failover** — Local Docker Compose only; Phase 2+ concern
- **Container image signing or OCI attestation** — Deferred to Phase 2
- **Full load testing** — Graceful shutdown tested with simple signal, not under concurrent load
- **pgAdmin auth hardening** — Completely removed instead of adding auth layer

## Implementation Approach

**Strategy**: Incremental hardening across 5 phases, each testable and backward-compatible:

1. **Compose configuration hardening** — Resource limits, production overrides, volume cleanup
2. **Secrets validation** — Pre-startup checks in entrypoint before uvicorn binds
3. **Logging infrastructure** — Docker driver rotation + JSON structure prep
4. **Testing gates** — CI shutdown and startup order verification
5. **Documentation** — Migration path, deployment guide, env variable reference

**Backward compatibility**: All changes are additive (new docker-compose.prod.yml, enhanced entrypoint) or replacement (removed pgAdmin, chroma_db volume). Phase 1 deployments can upgrade incrementally: add env validation → rotate logs → add compose overrides → update CI tests.

**Verification approach**: Each phase has automated tests (lint, docker-compose validate) and manual verification steps (manual SIGTERM, health check inspection, log rotation check).

---

## Phase 1: Compose Configuration & Resource Limits

### Overview

Harden docker-compose.yml with CPU limits, production compose overrides, log rotation driver configuration, and remove deprecated ChromaDB volume. This phase closes the resource-bounding gap (agents can't saturate host) and establishes dev/prod separation pattern.

### Changes Required:

#### 1. Update docker-compose.yml with CPU limits and log rotation

**File**: `docker-compose.yml`

**Intent**: Add CPU resource limits to the api service (preventing runaway agents from saturating host), configure Docker json-file log driver for automatic rotation (preventing unbounded disk growth), and remove deprecated chroma_db volume.

**Contract**: 
- `api` service gains `deploy.resources.limits.cpus: '2'` (hard cap) and `deploy.resources.limits.cpu_reservation: '1'` (soft reservation)
- Both `db` and `api` services gain `logging` driver configuration with Docker json-file driver: `max-size: "100m"`, `max-file: "10"`
- Remove `chroma_db` volume definition (lines 93-95 in current) entirely
- Remove `chroma_db` volume mount from `api` service (line 68 in current)

```yaml
# Example for api service logging driver
logging:
  driver: "json-file"
  options:
    max-size: "100m"
    max-file: "10"
```

#### 2. Create docker-compose.prod.yml with production overrides

**File**: `docker-compose.prod.yml` (new file)

**Intent**: Define production-specific overrides that remove development-only services (pgAdmin), disable bind mounts for source code (reduces attack surface), and tighten resource limits further if needed.

**Contract**: New file at project root; uses Docker Compose v3 override syntax. Overrides:
- Remove `api` service's bind mount volumes for `/src`, `/ui`, `/alembic`, `main.py`, `ui.py` (keep only `/app/data/cv` for CV files and named volumes)
- Set `AGENTIC_HIRE_ENVIRONMENT: production` and `AGENTIC_HIRE_LOG_LEVEL: INFO` (vs. DEBUG in base)
- Optionally tighten memory limits in production (e.g., api: 3G limit, 1.5G reservation)

```yaml
# Minimal production override example
services:
  api:
    environment:
      AGENTIC_HIRE_ENVIRONMENT: production
      AGENTIC_HIRE_LOG_LEVEL: INFO
    volumes:
      # Remove bind mounts for src code; keep data
      - ./data/cv:/app/data/cv
      - chroma_db_new:/app/data/chroma_db
    deploy:
      resources:
        limits:
          memory: 3G
        reservations:
          memory: 1.5G
```

#### 3. Create MIGRATION.md for Phase 1 → F-05 upgrade

**File**: `MIGRATION.md` (new file)

**Intent**: Document the upgrade path for users running Phase 1 systems, including ChromaDB volume removal, environment variable changes, and safe migration steps.

**Contract**: New file at project root. Sections:
- **Overview**: What changed, why (log rotation, resource limits, pgAdmin removal, ChromaDB deprecation)
- **Before upgrading**: Verify pgvector migration complete (all CV embeddings in PostgreSQL)
- **Upgrade steps**: Pull new code, remove old chroma_db volume (`docker volume rm agentic-hire-ai_chroma_db`), restart with `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up`
- **Rollback**: Keep old volume until confident pgvector is stable
- **Environment variables**: New log level options, production flag

### Success Criteria:

#### Automated Verification:

- docker-compose validate passes: `docker-compose config > /dev/null`
- docker-compose prod override validates: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml config > /dev/null`
- No references to `chroma_db` in docker-compose.yml: `grep -c chroma_db docker-compose.yml` should be 0
- Log driver configuration present: `grep -A2 "logging:" docker-compose.yml` shows json-file driver
- CPU limits present: `grep "cpus:" docker-compose.yml` shows '2' and '1'

#### Manual Verification:

- `docker-compose up` starts successfully; both services healthy after 30s
- `docker logs agentic-hire-api` shows plain text logs (Phase 1 baseline)
- Logs rotate: Create a test container, fill `/app/logs` with large files, verify json-file driver would rotate after 100MB
- `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up` starts without errors
- Production compose excludes `/src` mount (verify source code not in container volumes)

---

## Phase 2: Entrypoint Validation & Secrets Hardening

### Overview

Enhance docker-entrypoint.sh with pre-startup validation of required environment variables (AGENTIC_HIRE_OPENROUTER_API_KEY, AGENTIC_HIRE_JWT_SECRET_KEY, AGENTIC_HIRE_DATABASE_URL). This phase eliminates slow health check timeouts caused by bad configuration, replacing them with fast failure (<1s) and clear error messages.

### Changes Required:

#### 1. Enhance docker-entrypoint.sh with environment variable validation

**File**: `docker-entrypoint.sh`

**Intent**: Add validation logic at the start of the script (before any service checks) to verify all required environment variables are set and non-empty. Fail with clear error message if any required var is missing.

**Contract**: New section at the start of docker-entrypoint.sh (after `set -e`, before database checks). Checks:
- `AGENTIC_HIRE_OPENROUTER_API_KEY` — required for LLM calls
- `AGENTIC_HIRE_JWT_SECRET_KEY` — required for token signing
- `AGENTIC_HIRE_DATABASE_URL` — required for database connection

Exit with code 1 and descriptive error if any are missing.

```bash
# Add after line 3 (set -e), before database extraction:
echo "=== Validating required environment variables ==="
REQUIRED_VARS=("AGENTIC_HIRE_OPENROUTER_API_KEY" "AGENTIC_HIRE_JWT_SECRET_KEY" "AGENTIC_HIRE_DATABASE_URL")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
done
echo "✓ All required variables are set"
```

#### 2. Document secret generation in .env.example

**File**: `.env.example`

**Intent**: Update template to clarify which variables are required (must be set before docker-compose up), which are optional, and provide generation commands for secrets.

**Contract**: Update .env.example with clear sections:
- **Required secrets** (must set before running):
  - `AGENTIC_HIRE_OPENROUTER_API_KEY` — LLM provider key
  - `AGENTIC_HIRE_JWT_SECRET_KEY` — Generated with: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
  - `AGENTIC_HIRE_DATABASE_URL` — PostgreSQL connection string
- **Optional (with defaults)**:
  - `AGENTIC_HIRE_ORIOSEARCH_BASE_URL`
  - `AGENTIC_HIRE_LOG_LEVEL`
  - `AGENTIC_HIRE_ENVIRONMENT`

### Success Criteria:

#### Automated Verification:

- Entrypoint script passes syntax check: `bash -n docker-entrypoint.sh`
- Variable validation logic present: `grep -c "AGENTIC_HIRE_OPENROUTER_API_KEY" docker-entrypoint.sh` should be >= 1
- Exit on missing var: Run entrypoint with missing AGENTIC_HIRE_OPENROUTER_API_KEY, verify exit code is 1
- .env.example updated: `grep "REQUIRED\|OPTIONAL" .env.example` shows clear sections

#### Manual Verification:

- Start container without AGENTIC_HIRE_OPENROUTER_API_KEY: `docker run --rm [image] /app/docker-entrypoint.sh` fails with clear error (not health check timeout)
- Start container with all required vars: container runs successfully
- Error message is clear and actionable (e.g., "ERROR: Required environment variable AGENTIC_HIRE_OPENROUTER_API_KEY is not set")

---

## Phase 3: Logging Hardening & JSON Structure

### Overview

Configure loguru for JSON structured logging and prepare for Phase 2 observability integration. This phase enables log aggregation (Datadog, Splunk, Loki) while maintaining plain text output for local development.

### Changes Required:

#### 1. Refactor loguru configuration for JSON support

**File**: `src/config/logging.py`

**Intent**: Add JSON sink configuration to loguru setup, enabling structured logs for machine parsing while keeping plain text as default for human debugging. Phase 2 will hook the JSON output into a log aggregation platform.

**Contract**: Extend `setup_logging(debug: bool = False)` function to:
- Keep current plain text format (debug and production modes unchanged)
- Add optional JSON sink (disabled by default, enabled via environment variable `AGENTIC_HIRE_JSON_LOGS=true`)
- JSON format: `{"timestamp": "...", "level": "INFO", "message": "...", "module": "...", "function": "..."}` (loguru's built-in JSON serialization)

```python
# Example JSON sink configuration (in setup_logging function)
if json_logs:  # Controlled by AGENTIC_HIRE_JSON_LOGS env var
    logger.add(
        sys.stdout,
        format="{message}",  # Raw JSON from serialize=True
        serialize=True,
        level=log_level,
    )
```

#### 2. Document log rotation and Phase 2 aggregation hooks

**File**: `docs/observability.md` (new file)

**Intent**: Document the logging architecture, how logs are currently rotated via Docker driver, and where Phase 2 will integrate log aggregation.

**Contract**: New documentation file with sections:
- **Current setup**: Docker json-file driver handles rotation (max-size: 100m, max-file: 10)
- **Structured logging**: JSON format available via AGENTIC_HIRE_JSON_LOGS=true
- **Phase 2 integration**: How to connect to Datadog/Splunk/Loki (template placeholders for API keys, endpoints)
- **Debugging**: How to view logs: `docker-compose logs -f api`, `docker logs --tail=100 agentic-hire-api`

### Success Criteria:

#### Automated Verification:

- loguru configuration passes syntax check: `python -m py_compile src/config/logging.py`
- JSON sink code present: `grep -c "serialize=True" src/config/logging.py` should be >= 1
- Documentation created: `test -f docs/observability.md && echo "exists"`
- Type hints intact: `mypy src/config/logging.py` passes without new errors

#### Manual Verification:

- Start API with plain text (default): `AGENTIC_HIRE_JSON_LOGS=false docker-compose up` produces readable logs
- Start API with JSON enabled: `AGENTIC_HIRE_JSON_LOGS=true docker-compose up` produces JSON lines (each line is valid JSON)
- Parse JSON logs: `docker-compose logs api | jq '.level'` extracts log level from JSON
- Log rotation works: Fill logs to >100MB, verify new file created (json-file driver handles automatic)

---

## Phase 4: Graceful Shutdown & CI Testing

### Overview

Implement and test graceful shutdown behavior (signal handling, in-flight request draining) and add CI gates for startup order verification and shutdown testing. This phase ensures safe container restarts and validates orderly service lifecycle.

### Changes Required:

#### 1. Add graceful shutdown test to CI pipeline

**File**: `tests/integration/test_graceful_shutdown.py` (new file)

**Intent**: Implement a test that starts docker-compose, allows a few seconds for startup, sends SIGTERM, and verifies all services exit cleanly within 30 seconds. This gate prevents regressions in signal handling.

**Contract**: New pytest test file with:
- `test_graceful_shutdown_api` — Start API service, verify startup, send SIGTERM, verify clean exit (no zombie processes)
- `test_graceful_shutdown_database` — Start DB service, verify startup, send SIGTERM, verify clean exit
- `test_docker_compose_up_wait` — Test `docker-compose up --wait` (requires Docker Compose 2.1+)

```bash
# Example test structure (bash, not pytest, for clarity):
docker-compose up -d
sleep 5  # Allow startup
docker-compose kill -s SIGTERM
wait_for_exit 30  # Verify all processes exit within 30s
echo "✓ Graceful shutdown successful"
```

#### 2. Add startup order validation to CI

**File**: `.github/workflows/ci.yml` (or equivalent CI config)

**Intent**: Add a CI step that validates `docker-compose up --wait` succeeds, ensuring health checks pass and services are ready before tests run.

**Contract**: New CI step that:
- Builds docker image if needed
- Runs `docker-compose up --wait` (Docker Compose 2.1+)
- Verifies exit code is 0 (all services healthy)
- Timeout: 60 seconds (catches hung startup)
- Runs before integration tests

```bash
# Example CI step
- name: "Verify startup order"
  run: docker-compose up --wait
```

#### 3. Document manual shutdown verification

**File**: `docs/testing.md` (update or create)

**Intent**: Document how to manually test graceful shutdown for development/validation.

**Contract**: New section with steps:
1. Start services: `docker-compose up`
2. Verify healthy: `docker-compose ps` shows "Up" status
3. Send SIGTERM: `docker-compose kill -s SIGTERM`
4. Verify clean exit: No error messages, `docker-compose ps` shows "Exited" or "Removing"
5. Check logs: `docker logs agentic-hire-api | tail` shows no crash traces

### Success Criteria:

#### Automated Verification:

- Graceful shutdown test file exists: `test -f tests/integration/test_graceful_shutdown.py`
- CI config includes startup order step: `grep -c "docker-compose up --wait" .github/workflows/ci.yml`
- Test passes: `pytest tests/integration/test_graceful_shutdown.py -v` succeeds
- Startup order validated in CI: `docker-compose up --wait` succeeds in under 60s
- Docker Compose version supports `--wait`: `docker-compose version | grep "version 2.1"`

#### Manual Verification:

- Manual shutdown test: `docker-compose up -d && sleep 5 && docker-compose kill -s SIGTERM && docker-compose ps` shows clean exit
- No zombie processes: `ps aux | grep uvicorn` shows no defunct processes after shutdown
- Logs show clean exit: `docker logs agentic-hire-api | tail -20` has no crash traces or warnings
- Health check reflected: `docker-compose ps` shows "Exited (0)" for graceful exit

---

## Phase 5: Documentation & Migration Path

### Overview

Write comprehensive migration documentation, environment variable reference, and deployment guide so users and operators understand the F-05 changes and can upgrade safely from Phase 1.

### Changes Required:

#### 1. Create comprehensive MIGRATION.md

**File**: `MIGRATION.md` (created in Phase 1; enhance here)

**Intent**: Detailed upgrade guide for Phase 1 → F-05 transition, covering data safety (ChromaDB removal), environment variables, and safe deployment.

**Contract**: Sections:
- **Overview**: What changed in F-05 (log rotation, resource limits, pgAdmin removed, ChromaDB deprecated, secrets hardening)
- **Prerequisites**: Verify pgvector migration (all CVs in PostgreSQL, not ChromaDB)
- **Step-by-step upgrade**:
  1. Backup Phase 1 compose: `cp docker-compose.yml docker-compose.yml.backup`
  2. Pull F-05 code
  3. Verify environment: All required vars set in `.env`
  4. Dry-run production compose: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml config`
  5. Start with prod overrides: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
  6. Verify health: `docker-compose ps` (all healthy), `docker logs agentic-hire-api | tail`
  7. Clean up old volume: `docker volume rm agentic-hire-ai_chroma_db` (only after 1 week successful operation)
- **Rollback**: How to revert to Phase 1 if issues arise
- **Troubleshooting**: Common issues (secrets not set, old volume conflict, log driver failures)

#### 2. Create environment variable reference

**File**: `docs/environment-variables.md` (new file)

**Intent**: Complete reference for all environment variables, their purpose, requirements, and defaults.

**Contract**: Table with:
- Variable name
- Required? (yes/no)
- Default value (if any)
- Purpose
- Example value
- Generation command (for secrets)

```markdown
| Variable | Required | Default | Purpose | Example |
|----------|----------|---------|---------|---------|
| AGENTIC_HIRE_OPENROUTER_API_KEY | Yes | — | LLM API key | sk-or-v1-... |
| AGENTIC_HIRE_JWT_SECRET_KEY | Yes | — | JWT signing secret | generated with `python -c 'import secrets; ...'` |
| ... | ... | ... | ... | ... |
```

#### 3. Update main README or create deployment guide

**File**: `docs/deployment.md` or update `README.md`

**Intent**: High-level deployment guide for running F-05 system (post-Phase 1) locally and documenting the hardening features.

**Contract**: Sections:
- **Quick start**: Clone, `.env` setup, `docker-compose up`
- **Production deployment**: Use docker-compose.prod.yml, set AGENTIC_HIRE_ENVIRONMENT=production
- **Health checks**: How to verify system is healthy
- **Resource requirements**: Hardware recommendations (8GB, 16GB, 32GB machines and corresponding limits)
- **Logging & monitoring**: How logs are rotated, JSON format availability, Phase 2 aggregation preview
- **Troubleshooting**: Common failures (startup timeout, log rotation, CPU limits)

### Success Criteria:

#### Automated Verification:

- MIGRATION.md exists: `test -f MIGRATION.md`
- Markdown syntax valid: `npm install -g markdownlint && markdownlint MIGRATION.md` (or pandoc check)
- environment-variables.md exists and is complete: `grep -c "AGENTIC_HIRE" docs/environment-variables.md` >= 6
- deployment.md or README updated: `grep -c "docker-compose.prod.yml\|ENVIRONMENT=production" docs/deployment.md` >= 1

#### Manual Verification:

- MIGRATION.md is clear and actionable: Follow the step-by-step upgrade on a real Phase 1 system
- Environment variable reference is complete: All vars in `.env.example` documented
- Troubleshooting section helps: Try a common failure (missing API key) and verify the troubleshooting guide addresses it
- README/deployment guide is beginner-friendly: A new operator can deploy F-05 system without prior knowledge

---

## Testing Strategy

### Unit Tests:

- docker-compose YAML validation: `docker-compose -f docker-compose.yml config > /dev/null`
- docker-compose.prod.yml validation: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml config > /dev/null`
- Entrypoint script syntax: `bash -n docker-entrypoint.sh`
- loguru JSON configuration: `python -m py_compile src/config/logging.py && mypy src/config/logging.py`

### Integration Tests:

- **Startup order** (Phase 4): `docker-compose up --wait` succeeds within 60s
- **Graceful shutdown** (Phase 4): `docker-compose kill -s SIGTERM` exits cleanly in <30s
- **Secrets validation** (Phase 2): Missing AGENTIC_HIRE_OPENROUTER_API_KEY causes fast exit with error
- **Log rotation** (Phase 1): Logs rotate at 100MB boundary (requires manual test with log filling)
- **Resource limits** (Phase 1): CPU limits honored (requires `docker stats` observation under load)

### Manual Testing Steps:

1. **Phase 1 verification**:
   - `docker-compose up -d`
   - `docker-compose ps` — verify both services healthy
   - `docker logs agentic-hire-api | head` — verify logs are rotating (json-file driver active)

2. **Phase 2 verification**:
   - Start without AGENTIC_HIRE_OPENROUTER_API_KEY: `AGENTIC_HIRE_OPENROUTER_API_KEY="" docker-compose up` — verify fast error
   - Start with all vars: container runs successfully

3. **Phase 3 verification**:
   - Enable JSON logs: `AGENTIC_HIRE_JSON_LOGS=true docker-compose up`
   - `docker logs agentic-hire-api | jq '.level'` — verify JSON parsing works

4. **Phase 4 verification**:
   - `docker-compose up -d && sleep 5 && docker-compose kill -s SIGTERM && docker-compose ps`
   - Verify "Exited (0)" status (clean shutdown)

5. **Phase 5 verification**:
   - Follow MIGRATION.md step-by-step on Phase 1 system
   - Verify all upgrades succeed and system is healthy post-upgrade

---

## Performance Considerations

**CPU limits**: API service capped at 2 cores (hard), 1 core (reserved). Vision LLM inference is CPU-bound; on 2-core machines, this may cause timeouts. Monitor during testing and adjust if needed (e.g., cpus: '4' on high-end dev machines).

**Memory limits**: API 4GB limit, 2GB reservation; DB 2GB default. On smaller machines (4GB total), may need adjustment. Documented in MIGRATION.md.

**Log rotation**: Docker json-file driver rotates at 100MB per file, max 10 files (1GB total). For long-running containers (weeks+), this requires external monitoring. Phase 2 will add log aggregation.

**Graceful shutdown timeout**: 30 seconds (uvicorn default) for draining requests. Production workloads with high concurrency may need 60s; configurable via compose `stop_grace_period`.

---

## Migration Notes

**Phase 1 → F-05 upgrade path**:
1. New chroma_db volume will NOT be created (removed from compose)
2. Old chroma_db volume persists on host; safe to delete after 1 week of successful pgvector operation
3. Environment variables: No new required vars added; only new optional vars (AGENTIC_HIRE_ENVIRONMENT, AGENTIC_HIRE_LOG_LEVEL control levels)
4. docker-compose.yml remains compatible (single source of truth); docker-compose.prod.yml is overlay
5. Backward compatibility: Phase 1 docker-compose.yml still works; F-05 just adds safety layers

**Data safety**:
- PostgreSQL data persists in `postgres_data` named volume (unchanged)
- CV files persist in `./data/cv` bind mount (unchanged)
- ChromaDB volume `chroma_db` removed; safe to delete after pgvector verified stable
- No data loss in upgrade if pgvector migration was successful in Phase 1

---

## References

- Research: `context/changes/docker-compose-hardening/research.md` — Comprehensive analysis of current gaps and hardening requirements
- Dockerfile: `Dockerfile:1-63` — Multi-stage build (unchanged by F-05)
- docker-compose.yml: `docker-compose.yml:1-102` — Current MVP compose (enhanced with CPU limits, log driver, volume removal)
- Entrypoint script: `docker-entrypoint.sh:1-63` — Current orchestration (enhanced with secrets validation)
- Logging config: `src/config/logging.py:1-24` — Current loguru setup (enhanced for JSON)
- Settings config: `src/config/settings.py:1-111` — pydantic-settings (reference for env var patterns)
- Environment template: `.env.example:1-16` — Current secrets template (enhanced in Phase 2)

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Compose Configuration & Resource Limits

#### Automated

- [x] 1.1 docker-compose.yml validates with CPU limits and log driver
- [x] 1.2 docker-compose.prod.yml validates with production overrides
- [x] 1.3 No references to chroma_db volume in compose
- [x] 1.4 MIGRATION.md created with upgrade path

#### Manual

- [x] 1.5 docker-compose up starts both services healthy
- [x] 1.6 Log rotation configured (json-file driver present)
- [x] 1.7 docker-compose.prod.yml overlay merges correctly
- [x] 1.8 Old docker-compose.yml still works (backward compat)

### Phase 2: Entrypoint Validation & Secrets Hardening

#### Automated

- [x] 2.1 Entrypoint script syntax valid
- [x] 2.2 Secrets validation code present in entrypoint
- [x] 2.3 Missing AGENTIC_HIRE_OPENROUTER_API_KEY causes exit code 1
- [x] 2.4 .env.example updated with required vs optional sections

#### Manual

- [x] 2.5 Container fails fast with clear error when required secret missing
- [x] 2.6 Container starts successfully with all required secrets
- [x] 2.7 Error message is actionable (not cryptic)

### Phase 3: Logging Hardening & JSON Structure

#### Automated

- [x] 3.1 loguru JSON sink configuration passes type check
- [x] 3.2 JSON sink code present and correctly formatted
- [x] 3.3 docs/observability.md created
- [x] 3.4 mypy src/config/logging.py passes

#### Manual

- [x] 3.5 Plain text logs readable (default mode)
- [x] 3.6 JSON logs valid when AGENTIC_HIRE_JSON_LOGS=true
- [x] 3.7 jq can parse JSON logs: docker logs api | jq '.level'

### Phase 4: Graceful Shutdown & CI Testing

#### Automated

- [x] 4.1 tests/integration/test_graceful_shutdown.py exists
- [x] 4.2 docker-compose up --wait passes in CI
- [x] 4.3 Graceful shutdown test passes: pytest -v
- [x] 4.4 CI config includes startup order validation

#### Manual

- [x] 4.5 Manual SIGTERM shutdown produces clean exit
- [x] 4.6 No zombie processes after shutdown
- [x] 4.7 Logs show no crash traces

### Phase 5: Documentation & Migration Path

#### Automated

- [x] 5.1 MIGRATION.md complete with step-by-step upgrade
- [x] 5.2 docs/environment-variables.md created with full reference
- [x] 5.3 docs/deployment.md or README updated
- [x] 5.4 Markdown syntax valid across all docs

#### Manual

- [x] 5.5 Follow MIGRATION.md on real Phase 1 system; verify upgrade succeeds
- [x] 5.6 Environment variable reference is complete and accurate
- [x] 5.7 Troubleshooting guide helps resolve common issues
