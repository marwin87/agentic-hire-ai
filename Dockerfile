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

# Install only runtime dependencies (poppler-utils for pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy only the virtual environment from builder (reduces image size ~60%)
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ ./src/
COPY main.py ui.py ./
COPY ui/ ./ui/

# Create data directories (cv will be mounted as a volume at runtime)
RUN mkdir -p /app/data/cv /app/data/chroma_db

# Add .venv to PATH so `python` and `streamlit` resolve to the virtualenv binaries
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Expose Streamlit port
EXPOSE 8501

# Health check: Streamlit /_stcore/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health').read()" || exit 1

# Run Streamlit with explicit host/port configuration
CMD ["streamlit", "run", "ui.py", "--server.port=8501", "--server.address=0.0.0.0"]
