# Migration Guide: Phase 1 → F-05 (Docker Compose Hardening)

This guide covers upgrading from the Phase 1 MVP Docker setup to the F-05 hardened configuration.

## What Changed in F-05

| Change | Impact |
|--------|--------|
| **Log rotation** | Docker json-file driver now rotates at 100MB per file (max 10 files = 1GB total). No more unbounded disk growth. |
| **CPU limits** | `api` service capped at 2 cores hard / 1 core reserved. Prevents runaway agents from saturating the host. |
| **ChromaDB volume removed** | `chroma_db` named volume removed from compose. pgvector (PostgreSQL) is now the sole vector store. |
| **Production compose overlay** | New `docker-compose.prod.yml` for production deployments (no source bind mounts, tighter limits, INFO logging). |
| **Secrets validation** | Entrypoint script now validates required environment variables before starting uvicorn. |
| **JSON logging** | Optional structured JSON logs via `AGENTIC_HIRE_JSON_LOGS=true` (ready for Phase 2 aggregation). |

---

## Before Upgrading

### 1. Verify pgvector migration is complete

All CV embeddings must be in PostgreSQL (pgvector), not ChromaDB. Run:

```bash
# Check if CV embeddings exist in pgvector
docker-compose exec db psql -U agentic_hire -c "SELECT COUNT(*) FROM cv_embeddings;"
```

If the count is 0 and you have CVs that were embedded under Phase 1, re-run CV ingestion after upgrading.

> **Note**: If you never successfully ran CV ingestion in Phase 1, there is nothing to migrate — proceed directly to upgrade.

### 2. Verify your .env has all required secrets

F-05 adds pre-startup validation that fails fast if required secrets are missing. Ensure your `.env` contains:

```bash
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-or-v1-...        # Required
AGENTIC_HIRE_JWT_SECRET_KEY=<generated-secret>       # Required
AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://...   # Required
```

Generate a fresh JWT secret if needed:
```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

---

## Upgrade Steps

### Step 1: Backup current configuration

```bash
cp docker-compose.yml docker-compose.yml.phase1.backup
```

### Step 2: Pull F-05 code

```bash
git pull origin master
```

### Step 3: Dry-run validation

Validate both compose files parse correctly before restarting:

```bash
# Validate base compose
docker-compose config > /dev/null && echo "✓ Base compose valid"

# Validate with production overrides
docker-compose -f docker-compose.yml -f docker-compose.prod.yml config > /dev/null && echo "✓ Prod overlay valid"
```

### Step 4: Stop current services

```bash
docker-compose down
```

### Step 5: Start with F-05 configuration

**Development** (source bind mounts for live reload, now via dev overlay):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**Production** (no source bind mounts, INFO logging, tighter limits):

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Step 6: Verify health

```bash
# Both services should show "Up" and "(healthy)"
docker-compose ps

# Tail recent API logs
docker logs --tail=50 agentic-hire-api
```

### Step 7: Clean up old ChromaDB volume (optional, after 1 week)

Once you're satisfied the system is running correctly on pgvector:

```bash
# List existing volumes
docker volume ls | grep chroma

# Remove if present (safe after pgvector is confirmed working)
docker volume rm agentic-hire-ai_chroma_db
```

> **Wait at least 1 week** before removing the old volume. If something goes wrong and you need to roll back to Phase 1 temporarily, the volume data will still be available.

---

## Rollback

If you need to revert to Phase 1:

```bash
# Stop F-05 services
docker-compose down

# Restore Phase 1 compose
cp docker-compose.yml.phase1.backup docker-compose.yml

# Restart Phase 1
docker-compose up -d
```

---

## Troubleshooting

### "Required environment variable X is not set"

The entrypoint now validates secrets before starting. Add the missing variable to your `.env` file.

Common causes:
- `AGENTIC_HIRE_OPENROUTER_API_KEY` missing → Add your OpenRouter API key
- `AGENTIC_HIRE_JWT_SECRET_KEY` missing → Generate with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
- `AGENTIC_HIRE_DATABASE_URL` missing → Add `postgresql+asyncpg://agentic_hire:your_password@db:5432/agentic_hire`

### Log rotation not working

The json-file driver is configured in docker-compose.yml. Rotation applies to **new log entries** after the container restarts. Old log data is in the existing JSON log file.

To verify the driver is active:
```bash
docker inspect agentic-hire-api | grep -A5 '"LogConfig"'
# Should show: "Type": "json-file", "Config": {"max-file": "10", "max-size": "100m"}
```

### API starts but health check fails

Check the API logs for startup errors:
```bash
docker logs agentic-hire-api 2>&1 | tail -30
```

Common cause: database not ready when API tries to connect. The entrypoint has a 30-second retry loop — if the db takes longer, increase `max_attempts` in `docker-entrypoint.sh`.

### "chroma_db" volume conflict on startup

If Docker complains about the old `chroma_db` volume, it's an orphan from Phase 1. It won't cause errors — Docker Compose simply won't create a new one. The volume data is still on your host at `data/chroma_db/`.

To suppress the warning and clean up:
```bash
docker volume rm agentic-hire-ai_chroma_db
```

### CPU limits causing agent timeouts

If Vision LLM inference is timing out under the 2-core limit (e.g., on a 2-core machine), increase the limit:

```bash
# In docker-compose.yml, edit the deploy.resources.limits.cpus value:
#   cpus: '4'  # Increase for high-end machines
```

See `docs/environment-variables.md` for full configuration reference.
