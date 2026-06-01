# Deployment Guide

AgenticHire AI runs as a two-service Docker Compose stack: a FastAPI backend and a PostgreSQL database with pgvector.

## Quick Start (Local Development)

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd agentic-hire-ai

# 2. Create your environment file
cp .env.example .env
# Edit .env — set AGENTIC_HIRE_OPENROUTER_API_KEY and generate a JWT secret:
python -c 'import secrets; print(secrets.token_urlsafe(32))'

# 3. Start services (with source bind mounts for live reload)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# 4. Verify both services are healthy
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
# Expected: both show "Up" and "(healthy)"

# 5. Check the API
curl http://localhost:8001/health
```

> **Dev vs prod compose files**: `docker-compose.yml` is the production-clean base (built image, no source mounts). `docker-compose.dev.yml` overlays source bind mounts for live reloading. `docker-compose.prod.yml` overlays production environment variables and tighter resource limits.

The API is exposed on port 8001 (host) → 8000 (container).

---

## Production Deployment

Use `docker-compose.prod.yml` as an overlay to the base compose file. It applies:
- `AGENTIC_HIRE_ENVIRONMENT=production`
- `AGENTIC_HIRE_LOG_LEVEL=INFO`
- Only the `data/cv` bind mount (no source code mounts)
- Tighter memory/CPU reservations

```bash
# Validate the merged config before starting
docker compose -f docker-compose.yml -f docker-compose.prod.yml config > /dev/null

# Start in production mode
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Verify health
docker compose ps
curl http://localhost:8001/health
```

### Environment Variables for Production

At minimum, set these in your `.env` (or inject via secrets manager):

```bash
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-or-v1-...
AGENTIC_HIRE_JWT_SECRET_KEY=<generated-secret>
AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/agentic_hire
POSTGRES_USER=agentic_hire
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=agentic_hire
```

See `docs/environment-variables.md` for the full reference.

---

## Health Checks

Both services have Docker health checks configured:

| Service | Check | Interval |
|---------|-------|----------|
| `db` | `pg_isready -U agentic_hire` | Every 10s |
| `api` | `curl -f http://localhost:8000/health` | Every 30s |

**`docker compose up -d --wait`** waits until all health checks pass before returning — useful in scripts and CI:

```bash
docker compose up -d --wait --timeout 120
echo "All services healthy"
```

---

## Hardware Requirements

| Setup | RAM | CPU | Notes |
|-------|-----|-----|-------|
| Minimal dev | 4 GB | 2 cores | Expect slower Vision LLM processing |
| Recommended dev | 8 GB | 4 cores | Comfortable for concurrent runs |
| Production | 16 GB | 4+ cores | For sustained load with multiple users |

The `api` service is configured with:
- Hard limit: 4 GB RAM, 2 CPU cores
- Soft reservation: 2 GB RAM, 1 CPU core

Adjust in `docker-compose.yml` (`deploy.resources`) for your machine.

---

## Logging & Monitoring

### Viewing Logs

```bash
# Follow API logs
docker compose logs -f api

# Last 100 lines
docker logs --tail=100 agentic-hire-api

# All services
docker compose logs
```

### Log Rotation

Logs are rotated automatically by Docker's json-file driver:
- Max file size: 100 MB
- Max files kept: 10 (1 GB total)

To verify rotation is configured:
```bash
docker inspect agentic-hire-api | grep -A5 '"LogConfig"'
# Should show: "Type": "json-file", "Config": {"max-file": "10", "max-size": "100m"}
```

### Structured JSON Logs

Enable for log aggregation pipelines (Datadog, Splunk, Loki):

```bash
AGENTIC_HIRE_JSON_LOGS=true docker compose up -d
# JSON lines appear on stderr; plain text on stdout
docker logs agentic-hire-api 2>&1 | jq '.level'
```

See `docs/observability.md` for Phase 2 aggregation integration details.

---

## Graceful Shutdown

Use `docker compose stop` (not `kill`) to drain in-flight requests cleanly:

```bash
docker compose stop
docker compose ps -a
# Expected: "Exited (0)" for both services
```

Exit code 137 means Docker force-killed the container (SIGKILL after timeout). If you see this, see `docs/testing.md` for the manual shutdown verification procedure.

---

## Upgrading from Phase 1

See `MIGRATION.md` for the step-by-step upgrade guide, including:
- New required environment variables
- Rollback instructions

---

## Troubleshooting

### Container fails to start with "Required environment variable ... is not set"

The entrypoint validates secrets before starting uvicorn. Add the missing variable to `.env`.

### API health check keeps failing

```bash
docker logs agentic-hire-api 2>&1 | tail -30
```

Common causes:
- Database not ready: the entrypoint retries for 30 seconds; if `db` takes longer, check DB logs
- Migration failure: `alembic upgrade head` output is in the API startup logs
- Missing secret: look for `ERROR: Required environment variable` lines

### Port 8001 already in use

Another process is using port 8001. Either stop it or change the host port in `docker-compose.yml`:
```yaml
ports:
  - "8002:8000"  # Change 8001 to any free port
```

### CPU limits causing timeouts

Vision LLM inference (PDF parsing) is CPU-bound. If it's timing out on 2-core machines, increase the limit in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'
```

