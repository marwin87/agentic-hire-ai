"""Unit tests for Risk #7: JWT/OpenRouter key leakage into HTTP response bodies or log entries.

Phase 4 of the test-plan rollout (context/foundation/test-plan.md §3).
Four surfaces tested independently via dependency overrides and mocked graph calls.
"""

import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import Request
from httpx import ASGITransport, AsyncClient
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user, get_db
from src.api.main import app, global_exception_handler
from src.api.routes.workflows import search_jobs_stream
from src.api.schemas import OrchestrateRequest
from src.config.settings import config
from src.db import User

FAKE_SECRET = "sk-or-v1-FAKE-SECRET"


def _make_mock_user() -> User:
    user: User = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "security-test@example.com"
    return user


async def _mock_get_db() -> AsyncGenerator[AsyncSession, None]:
    yield AsyncMock(spec=AsyncSession)  # type: ignore[misc]


async def test_workflow_error_does_not_leak_exception_in_response() -> None:
    """Graph exception string must not appear in OrchestrateResponse.status."""
    mock_user = _make_mock_user()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = _mock_get_db

    try:
        with (
            patch("src.api.main.init_db", new_callable=AsyncMock),
            patch("src.api.main.get_agent_factory", return_value=MagicMock()),
            patch("src.api.routes.workflows.AgentFactory"),
            patch(
                "src.api.routes.workflows.get_cv_context_async",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch("src.api.routes.workflows.build_graph") as mock_build_graph,
        ):
            mock_graph = AsyncMock()
            mock_graph.ainvoke.side_effect = Exception(FAKE_SECRET)
            mock_build_graph.return_value = mock_graph

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/workflows/search-jobs",
                    json={"criteria": "Python developer"},
                )

        assert FAKE_SECRET not in response.text
    finally:
        app.dependency_overrides.clear()


async def test_streaming_error_does_not_leak_exception_in_sse() -> None:
    """SSE error event data.message must not contain the raw exception string."""
    mock_user = _make_mock_user()

    async def fake_astream_raises(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise Exception(FAKE_SECRET)
        yield  # makes this an async generator so astream() returns an iterable

    with (
        patch("src.api.routes.workflows.AgentFactory"),
        patch(
            "src.api.routes.workflows.get_cv_context_async",
            new_callable=AsyncMock,
            return_value="",
        ),
        patch("src.api.routes.workflows.build_graph") as mock_build_graph,
    ):
        mock_graph = MagicMock()
        mock_graph.astream = fake_astream_raises
        mock_build_graph.return_value = mock_graph

        streaming_response = await search_jobs_stream(
            OrchestrateRequest(criteria="Python developer"),
            user=mock_user,
            session=AsyncMock(),
        )

        chunks: list[str] = []
        async for chunk in streaming_response.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode())

    full_output = "".join(chunks)
    assert FAKE_SECRET not in full_output


async def test_500_handler_hides_exception_in_production_mode() -> None:
    """Global exception handler must not expose exception text when debug_mode=False.

    Regression guard: confirms the existing production-mode handler is already safe.
    """
    mock_request = MagicMock(spec=Request)
    mock_request.method = "GET"
    mock_request.url.path = "/api/test"

    with patch.object(config, "debug_mode", False):
        response = await global_exception_handler(mock_request, Exception(FAKE_SECRET))

    body = json.loads(response.body)
    assert FAKE_SECRET not in json.dumps(body)


async def test_startup_log_does_not_contain_database_password() -> None:
    """Startup log must not include the database password from the DSN."""
    log_messages: list[str] = []
    sink_id = logger.add(lambda msg: log_messages.append(str(msg)), format="{message}")

    try:
        with (
            patch("src.api.main.init_db", new_callable=AsyncMock),
            patch("src.api.main.get_agent_factory", return_value=MagicMock()),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ):
                pass  # lifespan startup runs on __aenter__, shutdown on __aexit__
    finally:
        logger.remove(sink_id)

    captured = "\n".join(log_messages)
    assert "dev_password" not in captured
