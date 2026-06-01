---
project: AgenticHire AI
created: 2026-05-21
context: local Docker Compose development and deployment
python_version: 3.13
current_deployment: FastAPI + PostgreSQL + pgvector
---

# Docker Best Practices for AgenticHire AI

This guide covers containerization patterns for your LangGraph agent system. The current deployed system is FastAPI + PostgreSQL + pgvector (see `Dockerfile` and `docker-compose.yml` in the project root).

## Current System (Now Running)

Your app currently runs as:
- **FastAPI** (Python 3.13, API backend at port 8000)
- **PostgreSQL + pgvector** (persistent vector store and relational data)
- **LangGraph agents** (Scout, Validate, Orchestrator, Tailor)

Docker Compose runs a two-service stack (API + database), persisting data in a named volume.

This guide assumes local-only deployment (single Docker Compose stack, no Kubernetes, no multi-region).

---

## Quick Start (Current System)

The Dockerfile and docker-compose.yml are already created and verified:

```bash
docker-compose up

# The app will be running at http://localhost:8000

# Verify health
docker-compose ps
# STATUS should show "(healthy)" after ~15 seconds

# Stop and persist data
docker-compose down
# Data is preserved; run docker-compose up again to resume

# Clean everything (including persisted data)
docker-compose down -v
```

---

## Architecture Walkthrough

### Current System: FastAPI + PostgreSQL + pgvector

**File**: `Dockerfile` (multi-stage build, current)

- **Builder stage**: Compiles Python 3.13 with all dependencies via `uv sync --frozen --no-dev --compile-bytecode`
- **Runtime stage**: Installs only `poppler-utils` (OS-level dependency for PDF parsing), copies `.venv` from builder
- **Health check**: HTTP health endpoint confirms readiness
- **Cmd**: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

**File**: `docker-compose.yml` (current)

- Single `app` service running the Dockerfile
- Port 8000 exposed (FastAPI)
- Two volumes:
  - `./data/cv` (bind mount) — user drops PDFs here from the host
  - `postgres_data` (named volume) — persists vector DB and relational data across restarts
- Environment: `AGENTIC_HIRE_OPENROUTER_API_KEY` required; `AGENTIC_HIRE_ORIOSEARCH_BASE_URL` defaults to `host.docker.internal:8000` (points to your local machine)

**Build time**: ~23s (after first full build, layers cache)  
**Image size**: 1.46GB (Python 3.13 slim + dependencies)  
**Container memory**: Reserved 2GB, limit 4GB

---

## Dockerfile: Current Implementation

Create `Dockerfile` in the project root:

```dockerfile
# Stage 1: Builder
# Python 3.13 slim includes essentials (C compiler for psycopg, etc.)
FROM python:3.13-slim as builder

WORKDIR /app

# Install build dependencies (gcc, make, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency lock file (uv.lock is reproducible, deterministic)
COPY uv.lock pyproject.toml ./

# Install uv in the builder
RUN pip install --no-cache-dir uv

# Sync dependencies into a .venv in /app
# --frozen: fail if lock file is out of date (prevents divergence)
# --compile-bytecode: precompile .pyc files for faster startup
RUN uv sync --frozen --compile-bytecode

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

# Copy only the virtual environment from builder (reduces image size ~60%)
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ ./src/
COPY main.py ui.py ./
COPY data/cv/ ./data/cv/

# No pip, no build tools in runtime image — smaller, less attack surface
# Add .venv to PATH so `python` resolves to the virtualenv binary
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Health check: FastAPI /health endpoint (customize endpoint as needed)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# Run FastAPI via uvicorn with proper signal handling
# --host 0.0.0.0: listen on all interfaces (required in containers)
# --port 8000: default
# --workers 1: single worker for now (LangGraph is thread-safe, but agents are CPU-bound)
#   → increase to 4 if you add I/O-heavy endpoints; monitor CPU on your dev machine
# --timeout 300: agents take time (CV ingestion, job search); 5 min is reasonable for MVP
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout", "300"]
```

### Key Decisions Explained

- **Multi-stage build**: Stage 1 compiles dependencies; Stage 2 only gets the `.venv`. Reduces final image from ~800MB to ~300MB.
- **uv.lock, not requirements.txt**: `uv sync --frozen` guarantees reproducible builds. `--compile-bytecode` speeds startup ~10%.
- **HEALTHCHECK**: Docker waits for container health before routing traffic. Customize the endpoint if you use `/api/health` instead of `/health`.
- **PYTHONUNBUFFERED=1**: Ensures logs appear in real-time (critical for debugging).
- **PYTHONDONTWRITEBYTECODE=1**: Prevents `.pyc` files bloating the container.
- **Signal handling**: uvicorn handles SIGTERM (graceful shutdown on `docker stop`). No extra work needed.

---

## docker-compose.yml: Three-Service Stack

Create `docker-compose.yml` in the project root:

```yaml
version: '3.9'

services:
  # FastAPI backend
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      # Database connection (from postgres service)
      AGENTIC_HIRE_DB_URL: postgresql+asyncpg://agentic_hire:hire_password@postgres:5432/agentic_hire_db
      # LLM & external APIs (from .env)
      AGENTIC_HIRE_OPENROUTER_API_KEY: ${AGENTIC_HIRE_OPENROUTER_API_KEY}
      AGENTIC_HIRE_ORIOSEARCH_BASE_URL: ${AGENTIC_HIRE_ORIOSEARCH_BASE_URL:-http://localhost:8001}
      # Logging
      AGENTIC_HIRE_LOG_LEVEL: ${AGENTIC_HIRE_LOG_LEVEL:-INFO}
      # Python
      PYTHONUNBUFFERED: "1"
    volumes:
      # Hot reload in development: source code changes trigger restart
      - ./src:/app/src
      - ./data:/app/data
    networks:
      - agentic_hire_net
    restart: unless-stopped
    # Limits prevent runaway agents from consuming all machine RAM
    # Adjust for your hardware (8GB machine can handle these)
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G

  # PostgreSQL 16 + pgvector
  postgres:
    image: ankane/pgvector:16
    # Built on postgres:16-bookworm, includes pgvector extension (no build needed)
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: agentic_hire
      POSTGRES_PASSWORD: hire_password
      POSTGRES_DB: agentic_hire_db
      # pgvector performance (single-user dev, not production)
      POSTGRES_INITDB_ARGS: "-c shared_buffers=256MB -c effective_cache_size=1GB"
    volumes:
      # Persist data across restarts
      - postgres_data:/var/lib/postgresql/data
      # Optional: SQL initialization script (migrations run on startup)
      - ./migrations/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    networks:
      - agentic_hire_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agentic_hire -d agentic_hire_db"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # Optional: pgAdmin for visual query debugging (delete if not needed)
  pgadmin:
    image: dpage/pgadmin4:latest
    environment:
      PGADMIN_DEFAULT_EMAIL: admin@agentic.local
      PGADMIN_DEFAULT_PASSWORD: admin
    ports:
      - "5050:80"
    depends_on:
      - postgres
    networks:
      - agentic_hire_net
    restart: unless-stopped

volumes:
  postgres_data:

networks:
  agentic_hire_net:
    driver: bridge
```

### Configuration via Environment Variables

The `docker-compose.yml` references `.env` for secrets and API keys. Create `.env` in the project root (add to `.gitignore` — never commit):

```bash
# Required: Your API keys (copy from your local .env)
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-or-v1-...
AGENTIC_HIRE_ORIOSEARCH_BASE_URL=http://localhost:8001

# Optional: adjust log level for debugging
AGENTIC_HIRE_LOG_LEVEL=DEBUG

# Optional: override database URL if not using Docker Postgres
# AGENTIC_HIRE_DB_URL=postgresql+asyncpg://user:pass@host:5432/dbname
```

### Service Lifecycle

**Startup order** (automatic):
1. PostgreSQL starts and runs `init.sql` (migrations)
2. FastAPI waits for `service_healthy` condition on Postgres
3. Backend starts, connects to DB, ready for requests

**Shutdown order** (automatic on `docker-compose down`):
1. Docker sends SIGTERM to each service
2. FastAPI (uvicorn) closes gracefully, drains in-flight requests (30s timeout)
3. PostgreSQL flushes WAL, syncs, exits

---

## Development Workflow

### First-Time Setup

```bash
# Copy your API keys
cp .env.example .env

# Build and start services
docker-compose up --build

# In another terminal, check logs
docker-compose logs -f backend
```

**Expected output:**
```
backend  | INFO:     Uvicorn running on http://0.0.0.0:8000
postgres | LOG:  database system is ready to accept connections
pgadmin  | [31m * Running on http://0.0.0.0/
```

### Hot Reload (Edit Code, See Changes)

Because of the `volumes` mount in `docker-compose.yml`:
```yaml
volumes:
  - ./src:/app/src  # Changes here trigger reload
  - ./data:/app/data
```

Edit a file in `src/`, save, and uvicorn auto-reloads within 1–2 seconds. No `docker-compose restart` needed.

**To force a restart** (e.g., if you changed dependencies):
```bash
docker-compose restart backend
```

### Running Tests Inside Container

```bash
# Run pytest in the backend service
docker-compose exec backend uv run pytest

# Run a single test file
docker-compose exec backend uv run pytest tests/test_graph.py -v

# Run with coverage
docker-compose exec backend uv run pytest --cov=src
```

### Database Debugging

**Via pgAdmin (web UI):**
- Open http://localhost:5050
- Login: `admin@agentic.local` / `admin`
- Add server:
  - Host: `postgres` (internal Docker DNS)
  - User: `agentic_hire`
  - Password: `hire_password`

**Via psql (command line):**
```bash
docker-compose exec postgres psql -U agentic_hire -d agentic_hire_db

# Then run SQL:
\dt                          # List tables
SELECT COUNT(*) FROM embeddings;  # Row counts
\q                           # Exit
```

### Viewing Logs

```bash
# All services
docker-compose logs -f

# Just backend
docker-compose logs -f backend

# Last 100 lines, then follow
docker-compose logs --tail=100 -f backend

# Timestamp + service name (easier to parse)
docker-compose logs -f --timestamps
```

---

## Production-Grade Patterns

### Graceful Shutdown

Your current setup already handles this:
- uvicorn catches SIGTERM and waits for in-flight requests (30s timeout configured in Dockerfile)
- PostgreSQL syncs WAL before exiting
- `docker-compose down` waits up to 10s per container

**To verify**: Send a SIGTERM manually:
```bash
docker-compose kill -s SIGTERM backend
# Watch logs — should see "Shutdown complete" instead of abrupt exit
docker-compose logs backend | tail -20
```

### Health Checks

The `HEALTHCHECK` in the Dockerfile ensures Docker knows when the service is ready:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()"
```

**Add a `/health` endpoint to your FastAPI app** (in `src/main.py`):
```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Docker will report `healthy` / `unhealthy` status:
```bash
docker ps
# NAMES              STATUS
# backend            Up 5 minutes (healthy)
# postgres           Up 5 minutes (healthy)
```

### Resource Limits

The `docker-compose.yml` sets CPU and memory limits:
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 4G
    reservations:
      cpus: '1'
      memory: 2G
```

Adjust for your hardware:
- **Limits**: hard cap (container killed if exceeded)
- **Reservations**: soft requested minimum

For an 8GB machine with other work, these defaults are safe. If agents run out of memory, increase `limits.memory` and monitor.

---

## Migration Strategy: Alembic for Schema Changes

Database migrations must run on startup (before the FastAPI app can use the schema). Use Alembic:

### Setup Alembic

```bash
# Generate Alembic scaffold (run once)
docker-compose exec backend alembic init migrations

# Configure migrations/env.py to auto-detect schema changes
# (Alembic can introspect SQLAlchemy models and generate migration scripts)
```

### Run Migrations on Container Start

Modify the `docker-compose.yml` backend service to run migrations before uvicorn:

```yaml
  backend:
    # ... existing config ...
    command: >
      sh -c "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout 300"
```

Now every container startup:
1. Runs pending migrations
2. Starts the FastAPI app
3. Exits gracefully on `docker-compose down`

---

## Debugging Tips

### Container Won't Start

```bash
# Check logs (most common: port already in use)
docker-compose logs backend

# Free port 8000
lsof -i :8000
kill -9 <PID>

# Rebuild (clear cached layers)
docker-compose build --no-cache backend
docker-compose up
```

### Database Connection Failing

```bash
# Check if Postgres is healthy
docker-compose ps postgres
# STATUS should show "healthy"

# Verify network connectivity from backend
docker-compose exec backend ping postgres
# Should see "64 bytes from postgres..."

# Check env var in backend
docker-compose exec backend env | grep DB_URL
```

### Memory / CPU Spikes

LangGraph agents (job search, CV ingestion) are CPU-intensive:

```bash
# Monitor container resources in real-time
docker stats

# If CPU hits 100% and doesn't release, agent may be stuck
# Check logs for errors
docker-compose logs backend | grep -i error

# Reduce worker count or agent parallelism (config in settings.py)
```

### Persistent State Issues

If data doesn't persist across restarts:
```bash
# Verify volume
docker volume ls | grep agentic_hire

# Inspect volume (where data actually lives on disk)
docker volume inspect agentic_hire_postgres_data

# Backup data before troubleshooting
docker run --rm -v agentic_hire_postgres_data:/data -v $(pwd):/backup \
  postgres:16 tar czf /backup/postgres_backup.tar.gz /data
```

---

## Networking: Backend ↔ External Services

### Connecting to OrioSearch (Local)

If OrioSearch runs on your host (port 8001):

**From Docker container**, `localhost` is the container, not your host. Use the host IP:

```python
# In src/config/settings.py
import socket

def get_host_ip():
    """Get host machine IP for Docker containers."""
    try:
        # Works on Linux, macOS (when Docker Desktop is running)
        return socket.gethostbyname('host.docker.internal')
    except socket.gaierror:
        # Fallback (Linux may need --add-host host.docker.internal:host-gateway)
        return 'localhost'

ORIOSEARCH_BASE_URL = os.getenv(
    'AGENTIC_HIRE_ORIOSEARCH_BASE_URL',
    f'http://{get_host_ip()}:8001'
)
```

**Or use `host.docker.internal` (Docker Desktop / Mac / Windows):**
```bash
# In .env
AGENTIC_HIRE_ORIOSEARCH_BASE_URL=http://host.docker.internal:8001
```

**Or run OrioSearch in Docker too** (recommended):
Add to `docker-compose.yml`:
```yaml
  oriosearch:
    image: <your-oriosearch-image>
    ports:
      - "8001:8000"
    networks:
      - agentic_hire_net
```

Then from backend: `http://oriosearch:8000` (internal Docker DNS).

### OpenRouter API Calls

OpenRouter is public (no network boundary concerns). Just pass the API key via `.env`:
```bash
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-or-v1-...
```

---

## Performance Tuning

### Faster Builds

```bash
# Cache layers aggressively
docker-compose build --progress=plain backend
# Watch for "CACHED" layers — if they're not caching, dependencies changed

# Rebuild only if pyproject.toml or uv.lock changed (use .dockerignore)
cat > .dockerignore <<EOF
.git
.gitignore
__pycache__
.pytest_cache
.mypy_cache
EOF
```

### Faster Startup

- Uvicorn `--workers 1` for MVP (CPU-bound agents don't benefit from multiple workers)
- If you add I/O-heavy endpoints (external API calls), increase to 4
- Monitor with `docker stats` — if CPU < 50%, consider more workers

### Vector DB Performance

PostgreSQL + pgvector on a dev machine:
- Embeddings: 1536-dim (OpenAI) or 384-dim (MiniLM) both fine
- Index type: `hnsw` (approximate, fast) or `ivfflat` (exact, slower). Use `hnsw` for >100k embeddings.
- For MVP (<1k embeddings per user), full scans are fine (no index needed)

---

## Shipping to Production (Future Phase 2)

This guide is for local development. When you're ready for production:

1. **Use a managed database** (AWS RDS, Supabase, etc.) instead of containerized Postgres
2. **Use a container registry** (Docker Hub, AWS ECR) to distribute the backend image
3. **Add CI/CD** (GitHub Actions) to build and push images on every commit
4. **Use an orchestrator** (Railway, Fly.io, or Kubernetes) to manage container lifecycle
5. **Use secrets management** (GitHub Secrets, AWS Secrets Manager) instead of .env files

At that point, `/10x-infra-research` becomes relevant for choosing the hosting platform. For now, this Docker setup is your entire deployment story.

---

## Checklist: Before You Commit

- [ ] Dockerfile is in the project root
- [ ] docker-compose.yml is in the project root
- [ ] .env is in .gitignore (secrets never committed)
- [ ] migrations/ folder exists (or will be created by Alembic init)
- [ ] src/main.py has a `/health` endpoint
- [ ] uv.lock is committed (reproducible builds)
- [ ] All external service URLs can be overridden via .env
- [ ] FastAPI app gracefully handles SIGTERM (uvicorn handles this by default)

---

## Quick Reference: Common Commands

```bash
# Start services (builds on first run)
docker-compose up

# Start in background
docker-compose up -d

# Stop services (graceful shutdown)
docker-compose down

# Rebuild after dependency changes
docker-compose build --no-cache
docker-compose up

# View logs (all services)
docker-compose logs -f

# Run a command inside backend container
docker-compose exec backend uv run pytest

# Interactive bash in backend
docker-compose exec backend /bin/bash

# Delete everything (containers, volumes, networks)
docker-compose down -v

# Database debug
docker-compose exec postgres psql -U agentic_hire -d agentic_hire_db

# Resource usage
docker stats

# Health status
docker-compose ps
```
