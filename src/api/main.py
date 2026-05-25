"""FastAPI application entry point for AgenticHire AI."""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from src.agents.agents import get_agent_factory
from src.api.routes import search, validation, scoring, evaluation
from src.config.settings import config


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Manage FastAPI application lifecycle (startup/shutdown)."""
    # Startup: initialize agent factory singleton
    logger.info("FastAPI startup: initializing AgentFactory...")
    factory = get_agent_factory()
    logger.info(f"AgentFactory initialized with LLM models: scout={config.scout_model_name}, orchestrator={config.orchestrator_model_name}, tailor={config.tailor_model_name}")
    yield
    # Shutdown: cleanup if needed
    logger.info("FastAPI shutdown: cleaning up resources...")


app = FastAPI(
    title="AgenticHire AI API",
    version="1.0.0",
    description="Autonomous multi-agent job application system",
    lifespan=lifespan,
)

# CORS middleware — permissive for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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
    logger.error(f"Unhandled exception in {request.method} {request.url.path}: {exc}", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": str(exc),
            "code": "INTERNAL_SERVER_ERROR",
        },
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for container orchestration and monitoring."""
    return {"status": "ok"}


# Register route routers
app.include_router(search.router)
app.include_router(validation.router)
app.include_router(scoring.router)
app.include_router(evaluation.router)
