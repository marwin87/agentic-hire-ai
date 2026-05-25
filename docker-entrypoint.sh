#!/bin/bash
set -e

echo "Starting AgenticHire AI application..."

# Extract host and port from DATABASE_URL
# Format: postgresql+asyncpg://user:password@host:port/db
if [ -n "$AGENTIC_HIRE_DATABASE_URL" ]; then
    DB_HOST=$(echo "$AGENTIC_HIRE_DATABASE_URL" | sed -n 's/.*@\([^:]*\).*/\1/p')
    DB_PORT=$(echo "$AGENTIC_HIRE_DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
    DB_PORT=${DB_PORT:-5432}

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

    if [ $? -eq 0 ]; then
        echo "Migrations completed successfully!"
    else
        echo "Warning: Migrations completed with warnings, but continuing..."
    fi
fi

echo ""
echo "=== Service Health Checks ==="

# Check FastAPI
echo "✓ FastAPI will start on http://0.0.0.0:8000"

# Check OrioSearch connectivity
ORIO_URL="${AGENTIC_HIRE_ORIOSEARCH_BASE_URL:-http://host.docker.internal:8003}"
echo "Checking OrioSearch at $ORIO_URL..."
if timeout 5 curl -s "$ORIO_URL/health" > /dev/null 2>&1; then
    echo "✓ OrioSearch connectivity check: OK at $ORIO_URL"
else
    echo "⚠ Warning: OrioSearch not responding at $ORIO_URL"
    echo "  Job search functionality will be unavailable until OrioSearch is running"
fi

echo "=== Starting FastAPI Server ==="
echo ""
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
