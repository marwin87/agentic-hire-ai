"""Integration tests for Risk #2: user data isolation.

Proves that the authenticated user's data is never visible to or modifiable
by a different authenticated user.

Test 1 — list isolation: GET /api/jobs returns only the requesting user's jobs.
Test 2 — write protection: create_or_update with user B's identity and user A's
  job ID leaves user A's row unchanged (regression guard for the Phase 2 fix).
"""

from datetime import datetime, timezone
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.api.dependencies import get_current_user, get_db
from src.api.main import app
from src.db.models import Job
from src.db.repositories import JobRepository


def _make_job_orm(job_id: str, user_id, title: str = "Test Job") -> Job:
    return Job(
        id=job_id,
        user_id=user_id,
        title=title,
        company="Test Corp",
        description="A test job",
        url=f"https://example.com/{job_id}",
        salary_range="$100k",
        discovered_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


async def _get_jobs(user, real_session) -> dict:
    """Make a GET /api/jobs request authenticated as the given user."""
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: real_session
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        response = await client.get("/api/jobs")
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
    return response.json()


async def test_job_list_scoped_to_authenticated_user(
    real_session, user_a, user_b
) -> None:
    """GET /api/jobs returns only the requesting user's own jobs.

    Seed one job for user A.  User B must see zero jobs.  User A must see
    exactly the seeded job.  The two requests are made sequentially so there
    is no dependency_overrides conflict between them.
    """
    job_id = f"isolation-list-{uuid4()}"
    job_a = _make_job_orm(job_id, user_a.id, title="User A's Job")
    await JobRepository.create_or_update(real_session, job_a)
    await real_session.flush()

    # User B must see zero jobs — user A's job must be invisible to them.
    data_b = await _get_jobs(user_b, real_session)
    assert (
        data_b["jobs"] == []
    ), "User B can see user A's jobs — list isolation is broken"

    # User A must see their own job (sanity check that the seed succeeded).
    data_a = await _get_jobs(user_a, real_session)
    ids_a = [j["id"] for j in data_a["jobs"]]
    assert job_id in ids_a, "User A cannot see their own seeded job"


async def test_create_or_update_cannot_overwrite_another_users_job(
    real_session, user_a, user_b
) -> None:
    """create_or_update with user B's identity and user A's job ID leaves user A's row unchanged.

    This test is a direct regression guard for the Phase 2 fix.
    Before the fix: the method looked up the existing job by ID alone,
    found user A's row, and overwrote its title with user B's value.
    After the fix: the ownership check (existing_job.user_id != job.user_id)
    causes an early return, leaving user A's row intact.

    To verify this test actually protects the risk, remove the ownership check
    from create_or_update — this test will fail, confirming it catches the gap.
    """
    job_id = f"isolation-write-{uuid4()}"

    # Step 1: seed user A's job with a known title.
    job_a = _make_job_orm(job_id, user_a.id, title="User A Original Title")
    await JobRepository.create_or_update(real_session, job_a)
    await real_session.flush()

    # Step 2: user B attempts create_or_update with the SAME job_id.
    # After the Phase 2 fix this is a no-op (ownership check returns early).
    job_b_attempt = _make_job_orm(job_id, user_b.id, title="User B Attack Title")
    await JobRepository.create_or_update(real_session, job_b_attempt)
    await real_session.flush()

    # Step 3: user A's row must be unchanged.
    result = await real_session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_a.id)
    )
    user_a_job = result.scalar_one_or_none()
    assert user_a_job is not None, "User A's job row was deleted"
    assert user_a_job.title == "User A Original Title", (
        f"User A's title was overwritten to '{user_a_job.title}' — "
        "create_or_update ownership check is not working"
    )
