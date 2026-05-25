"""Database session management and FastAPI dependency injection."""

from typing import AsyncGenerator, Optional
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from src.config.settings import AppConfig

# Global engine instance
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


async def init_db(config: AppConfig) -> None:
    """Initialize database engine and session factory."""
    global _engine, _session_factory

    _engine = create_async_engine(
        config.database_url,
        echo=config.debug_mode,
        future=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """Close database engine and dispose of connections."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


def get_session_factory() -> async_sessionmaker:
    """Get the global session factory."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for getting a database session.

    Usage in routes:
        @app.get("/items")
        async def get_items(session: AsyncSession = Depends(get_db)):
            result = await session.execute(select(Item))
            return result.scalars().all()
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session
