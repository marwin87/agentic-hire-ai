"""Smoke test: verifies the real-DB fixture stack connects and isolates correctly."""

from sqlalchemy import text


async def test_db_connection(real_session) -> None:
    """Real session connects to the test database."""
    result = await real_session.execute(text("SELECT 1 AS val"))
    row = result.fetchone()
    assert row is not None
    assert row.val == 1


async def test_savepoint_isolation(real_session, user_a) -> None:
    """user_a fixture creates a real User row visible within the transaction."""
    result = await real_session.execute(
        text("SELECT email FROM users WHERE email = :email"),
        {"email": "integration_user_a@test.com"},
    )
    row = result.fetchone()
    assert row is not None
    assert row.email == "integration_user_a@test.com"
