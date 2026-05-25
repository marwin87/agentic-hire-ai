# Docker Setup - Quick Reference

## What Changed

The application is now fully containerized with automatic database setup. When you run `docker-compose up`, **everything starts automatically**:

1. ✅ PostgreSQL database starts
2. ✅ Database becomes healthy (health check passes)
3. ✅ FastAPI service waits for database
4. ✅ Database migrations run automatically
5. ✅ FastAPI server starts and passes health check
6. ✅ Optional Streamlit UI starts (port 8501)

**No manual `alembic upgrade head` needed.**

## One-Line Start

```bash
docker-compose up -d
```

That's it. Everything is ready in ~25 seconds.

## New Files Added

| File | Purpose |
|------|---------|
| `docker-entrypoint.sh` | Startup script: waits for DB → runs migrations → starts FastAPI |
| `.github/workflows/ci.yml` | GitHub Actions CI/CD: tests, linting, type checking, Docker build |
| `DOCKER.md` | Comprehensive Docker guide with troubleshooting |
| `.env.example` | Updated with JWT secret key |

## Updated Files

| File | Changes |
|------|---------|
| `Dockerfile` | Added netcat/curl, copy alembic, use entrypoint script |
| `docker-compose.yml` | Use entrypoint for api service, added JWT_SECRET_KEY env var |

## Verify Everything Works

```bash
# Start services
docker-compose up -d

# Check all services are healthy
docker-compose ps
# All should show "Up" and "(healthy)" for api and db

# Test API health
curl http://localhost:8000/health

# Check migrations ran
docker-compose logs api | grep "Migrations"

# Test complete flow
curl -X POST http://localhost:8000/api/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPass123",
    "password_confirm": "TestPass123"
  }' | jq .access_token
```

## Important Environment Variables

### Required in .env:
- `AGENTIC_HIRE_OPENROUTER_API_KEY` — LLM API key
- `AGENTIC_HIRE_JWT_SECRET_KEY` — JWT signing key (generate: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)

### Defaults (work out of the box):
- `POSTGRES_USER=agentic_hire`
- `POSTGRES_PASSWORD=dev_password`
- `POSTGRES_DB=agentic_hire`
- `AGENTIC_HIRE_JWT_SECRET_KEY=dev_secret_key_change_in_production` (default in compose)

**⚠️ Change JWT_SECRET_KEY in production!**

## Accessing the Application

After `docker-compose up -d`:

- **API (FastAPI)**: `http://localhost:8000`
- **Health Check**: `http://localhost:8000/health`
- **Auth Page**: `http://localhost:8000/` (signup/login)
- **Dashboard**: `http://localhost:8000/dashboard` (after login)
- **Streamlit UI** (optional): `http://localhost:8501`
- **Database**: `localhost:5432` (postgres)

## CI/CD Pipeline

GitHub Actions (`.github/workflows/ci.yml`) runs automatically on push to `main`, `master`, `develop`:

1. **Lint & Type Check** — Black format, mypy strict mode
2. **Unit Tests** — pytest with mocked PostgreSQL
3. **Docker Build** — Verifies Dockerfile builds successfully
4. **Docker Compose Test** — Starts services, verifies health, tests API endpoints

All checks must pass before merging.

## Troubleshooting

```bash
# View API logs
docker-compose logs -f api

# View database logs
docker-compose logs -f db

# Check if migrations ran
docker-compose logs api | grep -i migration

# Check database connection
docker-compose exec api nc -zv db 5432

# Reset everything (deletes data!)
docker-compose down -v
docker-compose up -d
```

See `DOCKER.md` for detailed troubleshooting.

## Summary

✅ **Before**: Required manual `alembic upgrade head`  
✅ **Now**: Automatic migrations on startup via entrypoint script  
✅ **CI/CD**: Full pipeline with tests and Docker verification  
✅ **Documentation**: Comprehensive guide in DOCKER.md  

**Just run `docker-compose up -d` and everything works.**
