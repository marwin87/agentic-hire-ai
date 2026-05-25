"""Database configuration and connection pooling."""

from typing import Dict, Any, Type
from sqlalchemy.pool import NullPool, QueuePool, Pool
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def get_pool_class(environment: str) -> Type[Pool]:
    """Select appropriate connection pool based on environment."""
    if environment == "test":
        return NullPool
    return QueuePool


def configure_engine(
    database_url: str,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
    environment: str = "production",
) -> AsyncEngine:
    """Configure async SQLAlchemy engine with pgvector support."""
    pool_class = get_pool_class(environment)

    connect_args: Dict[str, Any] = {}
    if environment == "test":
        connect_args = {"check_same_thread": False}

    engine_kwargs: Dict[str, Any] = {
        "echo": echo,
        "future": True,
        "pool_pre_ping": True,
    }

    if pool_class != NullPool:
        engine_kwargs.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "poolclass": pool_class,
            }
        )
    else:
        engine_kwargs["poolclass"] = NullPool

    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    return create_async_engine(database_url, **engine_kwargs)
