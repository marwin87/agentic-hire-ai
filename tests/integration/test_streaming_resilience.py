"""Integration tests for Risk #3: SSE disconnect must not produce orphan evaluation writes.

Risk #3 (test-plan Phase 3): An SSE client disconnecting mid-stream must not leave
an orphan `run_graph()` task that writes evaluation rows after the stream closes.

Known limitation — scout-phase cancellation is unreliable:
`task.cancel()` during the Scout phase is absorbed by four `except Exception` blocks
in `src/agents/scout.py` (lines 174, 259, 300, 333) and one in
`src/tools/job_validator.py` (line 177). In Python 3.8+, CancelledError is a
BaseException subclass — these broad catches swallow it, meaning a cancel during
Scout does NOT reliably terminate the task.

This test bypasses that gap by stalling the mock graph AFTER all three node events
(validate_jobs, orchestrator, tailor) have been yielded. At that point `run_graph()`
is suspended inside `async for event in graph.astream(...)` — not inside a scout
`except Exception` block — so `task.cancel()` reliably delivers CancelledError to
`await gate.wait()`, and the persistence block is never reached.

Transport note: httpx + ASGITransport drains the full response body before closing,
so simulating disconnect via `async with client.stream():` early exit hangs the test
because the generator is blocked at `q.get()`. Instead, we call the route handler
directly and `aclose()` the `response.body_iterator` — exactly what Starlette does
when a real HTTP client drops the connection.

Failure signal: if the cancel+shield cleanup in `event_generator()` regresses (e.g.,
`task.cancel()` removed from the finally block), `run_graph()` will complete the
persistence block before `gen.aclose()` finishes, and this test will fail with a
non-None `match_score` for the test job.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.api.routes.workflows import search_jobs_stream
from src.api.schemas import OrchestrateRequest
from src.schema.state import JobOffer


def _make_resilience_job(job_id: str) -> JobOffer:
    return JobOffer(
        id=job_id,
        title="Streaming Resilience Test Engineer",
        company="Resilience Corp",
        description="A job for streaming resilience testing",
        url=f"https://example.com/{job_id}",
        salary_range="$130k",
        match_score=0.90,
        analysis="Strong streaming match",
    )


async def test_sse_disconnect_leaves_no_orphan_evaluation(
    async_client_a, real_session, user_a
) -> None:
    """On SSE disconnect after tailor event, no evaluation row must exist in the DB.

    Proves Risk #3: cancel+shield cleanup in event_generator() terminates run_graph()
    before the persistence block when the client disconnects post-tailor, pre-workflow_complete.

    The disconnect is simulated by calling search_jobs_stream() directly (bypassing the
    HTTP transport) and calling aclose() on response.body_iterator — the same path that
    Starlette takes when a real HTTP client drops the connection.
    """
    job_id = f"integ-resilience-{uuid4()}"
    job = _make_resilience_job(job_id)

    gate = asyncio.Event()  # intentionally never set — stalls run_graph() after tailor

    async def fake_astream_stalling(state, stream_mode=None):  # type: ignore[no-untyped-def]
        # Yield all three node events so shortlisted_jobs is fully populated.
        # This ensures the disconnect happens with a non-empty shortlisted_jobs —
        # the strongest possible signal that persistence would have run if cancel failed.
        yield {"validate_jobs": {"valid_jobs": [job], "rejected_jobs": []}}
        yield {"orchestrator": {"shortlisted_jobs": [job], "rejected_jobs": []}}
        yield {
            "tailor": {
                "applications": {job_id: {"found_job_offer": "Resilience test summary"}}
            }
        }
        # Block here — run_graph() is suspended at the next anext() call inside
        # `async for event in graph.astream(...)`, not inside any scout except block.
        # When gen.aclose() is called below, the generator's finally fires:
        # task.cancel() injects CancelledError directly into this await, skipping
        # the entire persistence block (workflows.py lines 417-451).
        await gate.wait()

    async with asyncio.timeout(10.0):
        with (
            patch("src.api.routes.workflows.AgentFactory") as mock_factory_cls,
            patch(
                "src.api.routes.workflows.get_cv_context_async", new_callable=AsyncMock
            ) as mock_cv,
            patch("src.api.routes.workflows.get_graph") as mock_get_graph,
        ):
            mock_factory_cls.return_value = MagicMock()
            mock_cv.return_value = ""

            mock_graph = MagicMock()
            mock_graph.astream = fake_astream_stalling
            mock_get_graph.return_value = mock_graph

            # Call the route handler directly — bypasses httpx/ASGITransport so
            # we can aclose() the body_iterator without the transport draining the body.
            streaming_response = await search_jobs_stream(
                OrchestrateRequest(criteria="Python engineer remote"),
                user=user_a,
                session=real_session,
            )
            gen = streaming_response.body_iterator

            # Consume SSE chunks until the tailor node_complete event, then break.
            # Each yield from event_generator() is one complete SSE line.
            async for chunk in gen:
                chunk_text = chunk.strip()
                if not chunk_text.startswith("data: "):
                    continue
                try:
                    event = json.loads(chunk_text[len("data: ") :])
                except json.JSONDecodeError:
                    continue
                if event.get("node") == "tailor" and event.get("status") == "complete":
                    break  # simulate disconnect — before workflow_complete and persistence

            # Explicitly close the generator — this is what Starlette does when the
            # HTTP client drops the connection. Triggers event_generator's finally:
            #   task.cancel() → CancelledError at gate.wait() → persistence skipped.
            await gen.aclose()

            # Yield to the event loop so the cancelled run_graph() task can complete
            # its own finally block (putting None sentinel in the queue).
            await asyncio.sleep(0.05)

    # DB-state assertion: no evaluation row for the disconnected job.
    # Either the job row was never created (expected path — persistence block skipped),
    # or if it somehow appeared, its match_score must be None.
    # A non-None match_score means persistence committed before cancellation —
    # the correct failure signal for a regression in the cancel+shield cleanup path.
    jobs_response = await async_client_a.get("/api/jobs")
    assert jobs_response.status_code == 200

    jobs_data = jobs_response.json()
    found = next((j for j in jobs_data["jobs"] if j["id"] == job_id), None)
    match_score_val = found["match_score"] if found else "N/A (job not in DB)"
    assert found is None or found["match_score"] is None, (
        f"Orphan evaluation detected for job {job_id!r}: "
        f"match_score={match_score_val} — "
        f"cancel+shield cleanup failed; persistence block ran before cancellation"
    )
