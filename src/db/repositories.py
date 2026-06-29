"""Async repository classes for database CRUD operations."""

from typing import List, Optional
from uuid import UUID

from datetime import datetime, timezone

from sqlalchemy import select, and_, cast, func, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import User, CVFile, CVEmbedding, Job, Evaluation

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import, import-untyped]
except ImportError:
    Vector = None  # type: ignore[assignment, misc]


class UserRepository:
    """Repository for User CRUD operations."""

    @staticmethod
    async def create(session: AsyncSession, email: str, password_hash: str) -> User:
        """Create a new user account."""
        user = User(email=email, password_hash=password_hash)
        session.add(user)
        await session.flush()
        return user

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """Retrieve user by email address."""
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: UUID) -> Optional[User]:
        """Retrieve user by ID."""
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()


class CVFileRepository:
    """Repository for CV file metadata CRUD operations."""

    @staticmethod
    async def create(
        session: AsyncSession, user_id: UUID, file_path: str, file_hash: str
    ) -> CVFile:
        """Create a new CV file metadata record."""
        cv_file = CVFile(user_id=user_id, file_path=file_path, file_hash=file_hash)
        session.add(cv_file)
        await session.flush()
        return cv_file

    @staticmethod
    async def get_latest_by_user(
        session: AsyncSession, user_id: UUID
    ) -> Optional[CVFile]:
        """Get the latest CV file for a user."""
        result = await session.execute(
            select(CVFile)
            .where(CVFile.user_id == user_id)
            .order_by(CVFile.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class CVEmbeddingRepository:
    """Repository for CV embedding CRUD and vector search operations."""

    @staticmethod
    async def bulk_insert(session: AsyncSession, embeddings: List[CVEmbedding]) -> None:
        """Bulk insert CV embeddings."""
        session.add_all(embeddings)
        await session.flush()

    @staticmethod
    async def search_by_user_and_query(
        session: AsyncSession,
        user_id: UUID,
        query_embedding: List[float],
        limit: int = 5,
    ) -> List[CVEmbedding]:
        """Search CV embeddings using vector similarity (cosine distance)."""
        if Vector is None:
            return []

        # Cast the query embedding to pgvector type for similarity search
        vector_query = cast(query_embedding, Vector(len(query_embedding)))

        result = await session.execute(
            select(CVEmbedding)
            .where(CVEmbedding.user_id == user_id)
            .order_by(CVEmbedding.embedding.cosine_distance(vector_query))  # type: ignore[attr-defined]
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def delete_by_user(session: AsyncSession, user_id: UUID) -> None:
        """Delete all embeddings for a user in a single statement."""
        await session.execute(delete(CVEmbedding).where(CVEmbedding.user_id == user_id))
        await session.flush()


class JobRepository:
    """Repository for Job CRUD operations."""

    @staticmethod
    async def create_or_update(session: AsyncSession, job: Job) -> Job:
        """Create or update a job posting."""
        existing = await session.execute(select(Job).where(Job.id == job.id))
        existing_job = existing.scalar_one_or_none()

        if existing_job:
            # Refuse to overwrite a job row that belongs to a different user.
            # Job.id is the primary key, so attempting an INSERT would raise an
            # IntegrityError — returning early is the correct no-op behaviour.
            if existing_job.user_id != job.user_id:
                return existing_job
            # Update own existing job
            existing_job.title = job.title
            existing_job.company = job.company
            existing_job.description = job.description
            existing_job.url = job.url
            existing_job.salary_range = job.salary_range
            await session.flush()
            return existing_job
        else:
            # Create new
            session.add(job)
            await session.flush()
            return job

    @staticmethod
    async def get_by_id(
        session: AsyncSession, job_id: str, user_id: UUID
    ) -> Optional[Job]:
        """Retrieve a job by ID, scoped to the owning user."""
        result = await session.execute(
            select(Job).where(Job.id == job_id, Job.user_id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user(
        session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> List[Job]:
        """Retrieve jobs for a user with pagination."""
        result = await session.execute(
            select(Job)
            .where(Job.user_id == user_id)
            .order_by(Job.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_user(session: AsyncSession, user_id: UUID) -> int:
        """Count jobs for a user."""
        result = await session.execute(
            select(func.count(Job.id)).where(Job.user_id == user_id)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_jobs_with_scores(
        session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> List[tuple[Job, Optional[float]]]:
        """Retrieve jobs with optional match scores for a user.

        Uses LEFT OUTER JOIN with Evaluation table so jobs without evaluations
        still appear with match_score=None.
        """
        result = await session.execute(
            select(Job, Evaluation)
            .where(Job.user_id == user_id)
            .outerjoin(
                Evaluation,
                (Evaluation.job_id == Job.id) & (Evaluation.user_id == user_id),
            )
            .order_by(Job.discovered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            (job, eval_record.match_score if eval_record else None)
            for job, eval_record in result.all()
        ]

    @staticmethod
    async def delete_by_id(session: AsyncSession, job_id: str, user_id: UUID) -> bool:
        """Delete a single job owned by the user. Returns True if deleted."""
        result = await session.execute(
            select(Job).where(Job.id == job_id, Job.user_id == user_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            return False
        await session.delete(job)
        await session.flush()
        return True

    @staticmethod
    async def delete_all_by_user(session: AsyncSession, user_id: UUID) -> int:
        """Delete all jobs for a user. Returns count deleted."""
        result = await session.execute(select(Job).where(Job.user_id == user_id))
        jobs = list(result.scalars().all())
        for job in jobs:
            await session.delete(job)
        await session.flush()
        return len(jobs)


class EvaluationRepository:
    """Repository for Evaluation CRUD operations."""

    @staticmethod
    async def create(session: AsyncSession, evaluation: Evaluation) -> Evaluation:
        """Create a new evaluation record."""
        session.add(evaluation)
        await session.flush()
        return evaluation

    @staticmethod
    async def get_by_user(
        session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> List[Evaluation]:
        """Retrieve evaluations for a user with pagination."""
        result = await session.execute(
            select(Evaluation)
            .where(Evaluation.user_id == user_id)
            .order_by(Evaluation.evaluated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_job_id(
        session: AsyncSession, job_id: str, user_id: UUID
    ) -> Optional[Evaluation]:
        """Retrieve evaluation for a specific job, scoped to the owning user."""
        result = await session.execute(
            select(Evaluation).where(
                Evaluation.job_id == job_id,
                Evaluation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_scores(
        session: AsyncSession,
        user_id: UUID,
        job_id: str,
        match_score: float,
        reasoning: str,
    ) -> None:
        """Update match score and orchestrator reasoning for an evaluation."""
        result = await session.execute(
            select(Evaluation).where(
                and_(Evaluation.user_id == user_id, Evaluation.job_id == job_id)
            )
        )
        evaluation = result.scalar_one_or_none()
        if evaluation:
            evaluation.match_score = match_score  # type: ignore[assignment]
            evaluation.orchestrator_reasoning = reasoning  # type: ignore[assignment]
            await session.flush()

    @staticmethod
    async def upsert(
        session: AsyncSession,
        user_id: UUID,
        job_id: str,
        match_score: float,
        orchestrator_reasoning: Optional[str],
        tailor_summary: Optional[str],
    ) -> None:
        """Insert or update an evaluation row for (user_id, job_id).

        Uses PostgreSQL ON CONFLICT DO UPDATE against uq_evaluations_user_job
        so re-running the workflow refreshes scores rather than creating duplicates.
        """
        stmt = (
            pg_insert(Evaluation)
            .values(
                user_id=user_id,
                job_id=job_id,
                match_score=match_score,
                orchestrator_reasoning=orchestrator_reasoning,
                tailor_summary=tailor_summary,
            )
            .on_conflict_do_update(
                constraint="uq_evaluations_user_job",
                set_={
                    "match_score": match_score,
                    "orchestrator_reasoning": orchestrator_reasoning,
                    "tailor_summary": tailor_summary,
                    "evaluated_at": datetime.now(timezone.utc),
                },
            )
        )
        await session.execute(stmt)


class SearchSessionRepository:
    """Repository for SearchSession CRUD operations."""

    @staticmethod
    async def create(
        session: AsyncSession, user_id: UUID, criteria: str, found_count: int = 0
    ) -> "SearchSession":  # type: ignore[name-defined]
        """Create a new search session record."""
        from src.db.models import SearchSession

        search_session = SearchSession(
            user_id=user_id, criteria=criteria, found_count=found_count
        )
        session.add(search_session)
        await session.flush()
        return search_session

    @staticmethod
    async def get_by_user(
        session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> List["SearchSession"]:  # type: ignore[name-defined]
        """Retrieve search sessions for a user with pagination, most recent first."""
        from src.db.models import SearchSession

        result = await session.execute(
            select(SearchSession)
            .where(SearchSession.user_id == user_id)
            .order_by(SearchSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
