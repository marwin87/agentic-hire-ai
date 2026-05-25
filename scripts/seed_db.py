"""Seed database with test data for local development."""

import asyncio
from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import config
from src.db import init_db, close_db, get_session_factory
from src.db.models import User, CVFile, CVEmbedding, Job, Evaluation


async def seed_database() -> None:
    """Populate database with test data for local development."""
    # Initialize database
    await init_db(config)
    print("✓ Database initialized")

    # Get session factory
    factory = get_session_factory()

    async with factory() as session:
        # Create test users
        user1 = User(
            id=uuid4(),
            email="alice@example.com",
            password_hash="$2b$12$...",  # bcrypt hash (placeholder)
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        user2 = User(
            id=uuid4(),
            email="bob@example.com",
            password_hash="$2b$12$...",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        session.add(user1)
        session.add(user2)
        await session.flush()
        print(f"✓ Created 2 test users: {user1.email}, {user2.email}")

        # Create CV files
        cv_file1 = CVFile(
            id=uuid4(),
            user_id=user1.id,
            file_path=f"/data/cv/{user1.id}.pdf",
            file_hash="abc123def456",
            ingested_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        session.add(cv_file1)
        await session.flush()
        print(f"✓ Created CV file for {user1.email}")

        # Create sample jobs
        jobs = [
            Job(
                id="job-1",
                user_id=user1.id,
                title="Senior Python Engineer",
                company="Tech Corp A",
                description="Looking for experienced Python developer with FastAPI knowledge",
                url="https://example.com/jobs/1",
                salary_range="$150k-$200k",
                discovered_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            ),
            Job(
                id="job-2",
                user_id=user1.id,
                title="Full Stack Engineer",
                company="Tech Corp B",
                description="Python backend + React frontend engineer",
                url="https://example.com/jobs/2",
                salary_range="$120k-$160k",
                discovered_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            ),
            Job(
                id="job-3",
                user_id=user2.id,
                title="Data Scientist",
                company="Data Company C",
                description="Machine learning and data analysis role",
                url="https://example.com/jobs/3",
                salary_range="$130k-$180k",
                discovered_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            ),
        ]

        for job in jobs:
            session.add(job)
        await session.flush()
        print(f"✓ Created 3 sample jobs")

        # Create sample evaluations
        evaluations = [
            Evaluation(
                id=uuid4(),
                user_id=user1.id,
                job_id="job-1",
                match_score=0.92,
                orchestrator_reasoning="Excellent match: requires Python, FastAPI, PostgreSQL - all your core skills",
                tailor_summary="Strong opportunity, worth applying immediately",
                evaluated_at=datetime.now(UTC),
            ),
            Evaluation(
                id=uuid4(),
                user_id=user1.id,
                job_id="job-2",
                match_score=0.78,
                orchestrator_reasoning="Good match: Python backend is perfect, React is learnable",
                tailor_summary="Good opportunity, competitive role",
                evaluated_at=datetime.now(UTC),
            ),
            Evaluation(
                id=uuid4(),
                user_id=user2.id,
                job_id="job-3",
                match_score=0.85,
                orchestrator_reasoning="Strong match: data science role aligns with your background",
                tailor_summary="Excellent fit for your profile",
                evaluated_at=datetime.now(UTC),
            ),
        ]

        for evaluation in evaluations:
            session.add(evaluation)
        await session.flush()
        print(f"✓ Created 3 sample evaluations")

        # Commit
        await session.commit()
        print("\n✅ Database seeding complete!")
        print(f"   Users: alice@example.com, bob@example.com")
        print(f"   Jobs: 3 positions (2 for alice, 1 for bob)")
        print(f"   Evaluations: 3 scores created")


async def main() -> None:
    """Main entry point."""
    try:
        await seed_database()
    except Exception as exc:
        print(f"❌ Error seeding database: {exc}")
        raise
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
