"""Database module for async SQLAlchemy with pgvector support."""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, create_async_engine as create_async_engine_internal, async_sessionmaker

__all__ = ["get_db_session", "create_engine"]


async def create_engine(database_url: str) -> AsyncEngine:
    """Create async database engine."""
    return create_async_engine_internal(
        database_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


async def get_db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection helper for FastAPI routes."""
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session_factory() as session:
        yield session
