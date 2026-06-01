# Docker Deployment Guide

AgenticHire AI can be run entirely in Docker with PostgreSQL and FastAPI backend.

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- `.env` file with required API keys

### Running the Application

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your API keys
nano .env

# Start all services (database + API server)
docker-compose up -d

# View logs
docker-compose logs -f api
```

The application will be available at:
- **FastAPI (JSON API)**: `http://localhost:8000`
- **Health check**: `http://localhost:8000/health`
- **Authentication**: `http://localhost:8000/` (auth.html)
- **Dashboard**: `http://localhost:8000/dashboard` (after login)

### Database Migrations

Migrations run **automatically** when the API service starts. If you need to manually run migrations:

```bash
# Run migrations inside the container
docker-compose exec api alembic upgrade head

# Check migration status
docker-compose exec api alembic current
```

## Services

### Database (`db`)
- **Image**: `pgvector/pgvector:pg17`
- **Port**: 5432
- **Volumes**: `postgres_data` (persists across restarts)
- **Health Check**: Enabled (waits for service to be healthy before API starts)

### API (`api`)
- **Service**: FastAPI REST API with JWT authentication
- **Port**: 8000
- **Entrypoint**: Automatically waits for DB, runs migrations, starts server
- **Depends On**: `db` (with health check)
- **Volumes**:
  - `./data/cv:/app/data/cv` — CV PDFs from host

## Environment Variables

Create `.env` file with these required variables:

```bash
# Required: OpenRouter API key for LLM
AGENTIC_HIRE_OPENROUTER_API_KEY=sk-...

# PostgreSQL (optional if using Docker)
POSTGRES_USER=agentic_hire
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=agentic_hire

# Optional: OrioSearch service (for job discovery)
AGENTIC_HIRE_ORIOSEARCH_BASE_URL=http://host.docker.internal:8000

# Optional: Logging level
AGENTIC_HIRE_LOG_LEVEL=INFO
```

## Common Commands

```bash
# Start services in background
docker-compose up -d

# View logs for API service
docker-compose logs -f api

# View logs for database
docker-compose logs -f db

# Stop all services
docker-compose down

# Stop and remove all data (volumes)
docker-compose down -v

# Restart a specific service
docker-compose restart api

# Shell into API container
docker-compose exec api bash

# Run a command in API container
docker-compose exec api alembic current
```

## Testing

### Manual API Testing

```bash
# Sign up a new user
curl -X POST http://localhost:8000/api/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "TestPassword123",
    "password_confirm": "TestPassword123"
  }'

# Response includes access_token and refresh_token
# Save the access_token

# Test authentication
TOKEN="<your-access-token>"
curl -X GET http://localhost:8000/api/dashboard \
  -H "Authorization: Bearer $TOKEN"
```

### Run Tests in Docker

```bash
# Run pytest inside the API container
docker-compose exec api pytest tests/ -v
```

## Database Persistence

- PostgreSQL data (including vector embeddings) persists in the `postgres_data` named volume
- Data survives `docker-compose down` (only removed with `docker-compose down -v`)

## Troubleshooting

### Database connection errors

```bash
# Check if database is ready
docker-compose exec db pg_isready -U agentic_hire

# Check database logs
docker-compose logs db
```

### API won't start

```bash
# Check API logs
docker-compose logs api

# Verify database connectivity
docker-compose exec api nc -zv db 5432
```

### Port conflicts

If ports 5432 or 8000 are already in use:

```bash
# Edit docker-compose.yml to change ports
# Change "5432:5432" to "5433:5432" (for example)

# Or stop conflicting services
docker ps
docker kill <container-id>
```

### Reset database (WARNING: deletes all data)

```bash
docker-compose down -v
docker-compose up -d
```

## Performance Tuning

Edit `docker-compose.yml` to adjust resource limits:

```yaml
deploy:
  resources:
    limits:
      memory: 4G          # Maximum memory
      cpus: 2            # Maximum CPUs
    reservations:
      memory: 2G         # Guaranteed memory
      cpus: 1            # Guaranteed CPUs
```

## Network Configuration

- Services communicate via internal Docker network `agentic-hire-net`
- Database host name inside containers: `db` (not `localhost`)
- External access uses localhost and mapped ports

On Linux, if you need to access Docker services from the host using `host.docker.internal`:

```bash
docker-compose up --add-host host.docker.internal:host-gateway
```

## CI/CD Integration

GitHub Actions pipeline (`.github/workflows/ci.yml`) includes:
- Linting (Black format check)
- Type checking (mypy)
- Unit tests (pytest with PostgreSQL)
- Docker image build test
- Docker Compose integration test

Tests run automatically on push to `main`, `master`, or `develop` branches.
