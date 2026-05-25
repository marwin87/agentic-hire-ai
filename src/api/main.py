"""FastAPI application entry point for AgenticHire AI."""

from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger

from src.agents.agents import get_agent_factory
from src.api.routes import search, validation, scoring, evaluation, auth
from src.api.dependencies import get_current_user
from src.config.settings import config
from src.db import init_db, close_db, User


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Manage FastAPI application lifecycle (startup/shutdown)."""
    # Startup: initialize database
    logger.info("FastAPI startup: initializing database...")
    await init_db(config)
    logger.info(f"Database initialized: {config.database_url}")
    logger.info("Note: Run 'alembic upgrade head' to apply pending migrations")

    # Startup: initialize agent factory singleton
    logger.info("FastAPI startup: initializing AgentFactory...")
    factory = get_agent_factory()
    logger.info(
        f"AgentFactory initialized with LLM models: scout={config.scout_model_name}, orchestrator={config.orchestrator_model_name}, tailor={config.tailor_model_name}"
    )

    yield

    # Shutdown: cleanup
    logger.info("FastAPI shutdown: closing database connections...")
    await close_db()
    logger.info("FastAPI shutdown: cleanup complete")


app = FastAPI(
    title="AgenticHire AI API",
    version="1.0.0",
    description="Autonomous multi-agent job application system",
    lifespan=lifespan,
)

# CORS middleware — restrict to trusted origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8501",
        "http://localhost:8000",
    ],  # Whitelist trusted origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next: Any) -> Any:
    """Log all incoming HTTP requests and responses."""
    logger.info(f"HTTP {request.method} {request.url.path} from {request.client}")
    response = await call_next(request)
    logger.info(f"HTTP {request.method} {request.url.path} → {response.status_code}")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler returning structured JSON error responses."""
    logger.error(
        f"Unhandled exception in {request.method} {request.url.path}: {exc}",
        exc_info=exc,
    )
    # In production, don't expose implementation details; log the full error server-side
    detail = "Internal server error"
    if config.debug_mode:
        detail = str(exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": detail,
            "code": "INTERNAL_SERVER_ERROR",
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration and monitoring."""
    return {"status": "ok"}


@app.get("/")
async def root() -> FileResponse:
    """Serve auth.html at root path."""
    auth_html = Path(__file__).parent.parent.parent / "ui" / "auth.html"
    return FileResponse(auth_html, media_type="text/html")


@app.get("/dashboard")
async def dashboard_page() -> FileResponse:
    """Serve dashboard.html for authenticated users."""
    dashboard_html = Path(__file__).parent.parent.parent / "ui" / "dashboard.html"
    return FileResponse(dashboard_html, media_type="text/html")


@app.get("/api/dashboard")
async def get_dashboard(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """API endpoint — returns user information for authenticated users."""
    return {
        "message": f"Welcome, {user.email}!",
        "user_id": str(user.id),
        "email": user.email,
    }


# Register route routers
app.include_router(auth.router)
app.include_router(search.router)
app.include_router(validation.router)
app.include_router(scoring.router)
app.include_router(evaluation.router)
