"""Integration tests for Risk #1: evaluation persistence survives a page reload.

Each test calls a workflow endpoint with a mocked graph (real DB session, real
repositories), then queries GET /api/jobs to assert that match_score is non-null
in the database — not just present in the workflow response JSON.

The distinction matters because both endpoints swallow all DB exceptions and return
HTTP 200 even when persistence fails. The only reliable signal is the DB row itself.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.schema.state import JobOffer


def _make_job(job_id: str) -> JobOffer:
    return JobOffer(
        id=job_id,
        title="Integration Test Engineer",
        company="Test Corp",
        description="A job for integration testing",
        url=f"https://example.com/{job_id}",
        salary_range="$120k",
        match_score=0.85,
        analysis="Strong match for the role",
    )


def _graph_result(job: JobOffer) -> dict:
    return {
        "shortlisted_jobs": [job],
        "rejected_jobs": [],
        "valid_jobs": [job],
        "applications": {job.id: {"founded_job_offer": "Excellent opportunity"}},
    }


async def test_sync_workflow_persists_match_score_to_db(
    async_client_a, real_session, user_a
) -> None:
    """After POST /api/workflows/search-jobs, GET /api/jobs returns non-null match_score.

    This proves the upsert call committed to the DB, not just that the workflow
    response JSON contained the score.
    """
    job_id = f"integ-sync-{uuid4()}"
    job = _make_job(job_id)

    with (
        patch("src.api.routes.workflows.AgentFactory") as mock_factory_cls,
        patch(
            "src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock
        ) as mock_cv,
        patch("src.api.routes.workflows.build_graph") as mock_build_graph,
    ):
        mock_factory_cls.return_value = MagicMock()
        mock_cv.return_value = ""

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=_graph_result(job))
        mock_build_graph.return_value = mock_graph

        response = await async_client_a.post(
            "/api/workflows/search-jobs",
            json={"criteria": "Python engineer remote"},
        )

    assert response.status_code == 200

    # Query the DB via GET /api/jobs — this is the "page reload" assertion.
    # If persistence failed, match_score would be None here even though
    # the workflow response above contained the score.
    jobs_response = await async_client_a.get("/api/jobs")
    assert jobs_response.status_code == 200

    jobs_data = jobs_response.json()
    found = next((j for j in jobs_data["jobs"] if j["id"] == job_id), None)
    assert found is not None, f"Job {job_id} not returned by GET /api/jobs"
    assert (
        found["match_score"] is not None
    ), "match_score is None — evaluation was not persisted to the DB"
    assert abs(found["match_score"] - 0.85) < 0.001


async def test_streaming_workflow_persists_match_score_to_db(
    async_client_a, real_session, user_a
) -> None:
    """After POST /api/workflows/search-jobs/stream, GET /api/jobs returns non-null match_score.

    The streaming persistence block runs inside run_graph() before the
    workflow_complete SSE frame is sent, so consuming the full stream guarantees
    the DB write (or its rollback) has completed before we query.
    """
    job_id = f"integ-stream-{uuid4()}"
    job = _make_job(job_id)

    # graph.astream is an async generator — must be assigned as an async def,
    # not as AsyncMock.return_value (which produces a non-iterable).
    async def fake_astream(state, stream_mode=None):  # type: ignore[no-untyped-def]
        # validate_jobs node populates acc["valid_jobs"] for job persistence
        yield {"validate_jobs": {"valid_jobs": [job], "rejected_jobs": []}}
        # orchestrator node populates acc["shortlisted_jobs"] for eval persistence
        yield {"orchestrator": {"shortlisted_jobs": [job], "rejected_jobs": []}}
        # tailor node populates acc["applications"] for tailor_summary
        yield {
            "tailor": {
                "applications": {job_id: {"founded_job_offer": "Stream test summary"}}
            }
        }

    with (
        patch("src.api.routes.workflows.AgentFactory") as mock_factory_cls,
        patch(
            "src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock
        ) as mock_cv,
        patch("src.api.routes.workflows.build_graph") as mock_build_graph,
    ):
        mock_factory_cls.return_value = MagicMock()
        mock_cv.return_value = ""

        mock_graph = MagicMock()
        mock_graph.astream = fake_astream
        mock_build_graph.return_value = mock_graph

        # Consume the full SSE stream until workflow_complete is received.
        # Persistence happens before workflow_complete is enqueued, so by the
        # time this loop exits the DB write is guaranteed to have completed.
        async with async_client_a.stream(
            "POST",
            "/api/workflows/search-jobs/stream",
            json={"criteria": "Python engineer remote"},
        ) as stream_response:
            assert stream_response.status_code == 200
            async for line in stream_response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if (
                    event.get("node") == "workflow"
                    and event.get("status") == "complete"
                ):
                    break

    # Same page-reload assertion as the sync test.
    jobs_response = await async_client_a.get("/api/jobs")
    assert jobs_response.status_code == 200

    jobs_data = jobs_response.json()
    found = next((j for j in jobs_data["jobs"] if j["id"] == job_id), None)
    assert found is not None, f"Job {job_id} not returned by GET /api/jobs"
    assert (
        found["match_score"] is not None
    ), "match_score is None — streaming persistence did not commit to the DB"
    assert abs(found["match_score"] - 0.85) < 0.001
