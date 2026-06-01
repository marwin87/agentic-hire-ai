"""Fixtures for integration tests that run against a real PostgreSQL database.

Prerequisites:
  1. Create the test database (one-time):
       python -c "
       import asyncio, asyncpg
       async def f():
           c = await asyncpg.connect('postgresql://agentic_hire:dev_password@localhost:5432/agentic_hire')
           await c.execute('CREATE DATABASE agentic_hire_test TEMPLATE template0')
           await c.close()
       asyncio.run(f())
       "
  2. Export the test DB URL before running:
       export AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire_test
     Or load from .env.test:
       export $(grep -v '^#' .env.test | xargs)

Design notes
------------
* Schema setup/teardown uses a sync session-scoped fixture calling asyncio.run() so it
  runs in an isolated event loop with no interference from pytest-asyncio's loop.
* Each test gets a fresh engine (NullPool) and connection in its own function-scoped
  event loop.  This avoids "Future attached to a different loop" errors that occur when
  a session-scoped async engine is reused across function-scoped test event loops.
* join_transaction_mode="create_savepoint" ensures that session.commit() inside the
  production endpoint commits to a savepoint rather than the outer transaction.
  conn.rollback() at teardown undoes all test data without truncating tables.
"""

import asyncio
import os

import pytest
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from src.api.dependencies import get_current_user, get_db
from src.api.main import app
from src.db.models import Base
from src.db.repositories import UserRepository

# Load .env.test so the test DB URL is available without a manual export.
# override=False so an already-exported env var takes precedence.
load_dotenv(".env.test", override=False)

_TEST_DATABASE_URL = os.environ.get(
    "AGENTIC_HIRE_DATABASE_URL",
    "postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire_test",
)

# Placeholder bcrypt hash — JWT is never decoded in integration tests because
# get_current_user is overridden via dependency_overrides.
_TEST_PASSWORD_HASH = "$2b$12$testvhashXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"


# ---------------------------------------------------------------------------
# Schema lifecycle — sync, session-scoped, runs in its own asyncio.run() loop
#
# Using a sync fixture with asyncio.run() avoids cross-loop issues that arise
# when a session-scoped async engine is shared with function-scoped test loops.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _schema_setup() -> None:  # type: ignore[return]
    """Create DB schema once before any integration tests; drop it at session end."""

    async def _setup() -> None:
        engine = create_async_engine(
            _TEST_DATABASE_URL, echo=False, future=True, poolclass=NullPool
        )
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        await engine.dispose()

    async def _teardown() -> None:
        engine = create_async_engine(
            _TEST_DATABASE_URL, echo=False, future=True, poolclass=NullPool
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# Session — async, function-scoped: fresh engine + SAVEPOINT per test
#
# NullPool ensures no connection pooling so the engine is fully disposed at
# the end of each test without leaving open connections to other event loops.
# ---------------------------------------------------------------------------


@pytest.fixture
async def real_session(_schema_setup):  # type: ignore[no-untyped-def]
    engine = create_async_engine(
        _TEST_DATABASE_URL, echo=False, future=True, poolclass=NullPool
    )
    async with engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await session.close()
        await conn.rollback()
    await engine.dispose()


# ---------------------------------------------------------------------------
# User fixtures — real rows inserted into the test DB via real_session
# ---------------------------------------------------------------------------


@pytest.fixture
async def user_a(real_session):  # type: ignore[no-untyped-def]
    user = await UserRepository.create(
        real_session,
        email="integration_user_a@test.com",
        password_hash=_TEST_PASSWORD_HASH,
    )
    await real_session.flush()
    return user


@pytest.fixture
async def user_b(real_session):  # type: ignore[no-untyped-def]
    user = await UserRepository.create(
        real_session,
        email="integration_user_b@test.com",
        password_hash=_TEST_PASSWORD_HASH,
    )
    await real_session.flush()
    return user


# ---------------------------------------------------------------------------
# HTTP clients — authenticated as user_a or user_b, injecting real_session
#
# ASGITransport is instantiated without async context manager so the FastAPI
# lifespan (init_db) does not run.  Both get_db and get_current_user are
# overridden so route handlers use the test session and fixture user without
# touching the dev database.
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_client_a(user_a, real_session):  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_current_user] = lambda: user_a
    app.dependency_overrides[get_db] = lambda: real_session
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    yield client
    await client.aclose()
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client_b(user_b, real_session):  # type: ignore[no-untyped-def]
    app.dependency_overrides[get_current_user] = lambda: user_b
    app.dependency_overrides[get_db] = lambda: real_session
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )
    yield client
    await client.aclose()
    app.dependency_overrides.clear()
