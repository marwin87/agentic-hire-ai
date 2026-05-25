# Stage 1: Builder
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
RUN uv sync --frozen --no-dev --compile-bytecode

# Stage 2: Runtime
FROM python:3.13-slim

WORKDIR /app

# Install only runtime dependencies (poppler-utils for pdf2image, netcat for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    netcat-openbsd \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only the virtual environment from builder (reduces image size ~60%)
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ ./src/
COPY main.py ui.py ./
COPY ui/ ./ui/

# Copy database migrations
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Copy and make entrypoint script executable
COPY docker-entrypoint.sh ./
RUN chmod +x /app/docker-entrypoint.sh

# Create data directories (cv will be mounted as a volume at runtime)
RUN mkdir -p /app/data/cv /app/data/chroma_db

# Add .venv to PATH so `python` and `streamlit` resolve to the virtualenv binaries
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose both Streamlit and FastAPI ports
EXPOSE 8501 8000

# Default to Streamlit (can be overridden by docker-compose)
CMD ["streamlit", "run", "ui.py", "--server.port=8501", "--server.address=0.0.0.0"]
