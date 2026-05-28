#!/bin/bash
set -e

# Forward SIGTERM to child processes and exit cleanly during the startup phase.
# Without this trap, bash ignores SIGTERM and Docker escalates to SIGKILL (exit 137).
# Once `exec uvicorn` replaces this bash process, uvicorn handles SIGTERM itself.
trap 'echo "Caught SIGTERM during startup, exiting..."; exit 0' SIGTERM SIGINT

echo "Starting AgenticHire AI application..."

# Validate required environment variables before doing anything else.
# Fails fast (<1s) with a clear error instead of a 5+ minute health check timeout.
echo "=== Validating required environment variables ==="
REQUIRED_VARS=("AGENTIC_HIRE_OPENROUTER_API_KEY" "AGENTIC_HIRE_JWT_SECRET_KEY" "AGENTIC_HIRE_DATABASE_URL")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "ERROR: Required environment variable $var is not set."
        echo "       Set it in your .env file or pass it via docker-compose environment."
        exit 1
    fi
done
echo "✓ All required environment variables are set"

# Extract host and port from DATABASE_URL using Python for reliable URL parsing
if [ -n "$AGENTIC_HIRE_DATABASE_URL" ]; then
    DB_HOST=$(python -c "from urllib.parse import urlparse; import os; print(urlparse(os.environ['AGENTIC_HIRE_DATABASE_URL']).hostname)")
    DB_PORT=$(python -c "from urllib.parse import urlparse; import os; print(urlparse(os.environ['AGENTIC_HIRE_DATABASE_URL']).port or 5432)")

    echo "Waiting for database at $DB_HOST:$DB_PORT..."

    # Wait for database to be ready
    max_attempts=30
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if nc -z "$DB_HOST" "$DB_PORT" 2>/dev/null; then
            echo "Database is ready!"
            break
        fi
        echo "Attempt $attempt/$max_attempts: Database not ready yet, waiting..."
        sleep 1
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "Error: Database did not become ready in time"
        exit 1
    fi

    # Run database migrations
    echo "Running database migrations..."
    alembic upgrade head
    echo "Migrations completed successfully!"
fi

echo ""
echo "=== Service Health Checks ==="

# Check OrioSearch connectivity
ORIO_URL="${AGENTIC_HIRE_ORIOSEARCH_BASE_URL:-http://host.docker.internal:8000}"
echo "Checking OrioSearch at $ORIO_URL..."
if timeout 5 curl -s "$ORIO_URL/health" > /dev/null 2>&1; then
    echo "✓ OrioSearch connectivity check: OK at $ORIO_URL"
else
    echo "⚠ Warning: OrioSearch not responding at $ORIO_URL"
    echo "  Job search functionality will be unavailable until OrioSearch is running"
fi

# Check FastAPI
echo "✓ FastAPI will start on http://0.0.0.0:8001 (accessible on host at http://localhost:8001)"

echo ""
echo "=== Starting FastAPI Server ==="
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
