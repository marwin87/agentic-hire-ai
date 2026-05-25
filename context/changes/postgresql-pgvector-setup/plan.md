---
title: PostgreSQL + pgvector setup (F-02)
created: 2026-05-25
type: foundation
complexity: high
---

# Implementation Plan: PostgreSQL + pgvector Setup (F-02)

## Context & Approach

This plan establishes the database layer for multi-user support and semantic search in AgenticHire AI. The system migrates from ChromaDB (single-user, in-memory) to PostgreSQL + pgvector (persistent, multi-user, vector-aware).

### Key Decisions
- **CV Storage**: Filesystem with metadata in Postgres (resolved Q2)
- **Migrations**: Alembic (SQLAlchemy) with version control
- **Async Driver**: asyncpg + SQLAlchemy async ORM for FastAPI compatibility
- **Vector Dimension**: Configurable (default 1536 for OpenRouter embeddings)
- **Test Data**: Seed script + pytest fixtures

### Dependencies & Unlocks
**Prerequisites**: None (can run in parallel with F-01, which is already done)

**Unlocks**:
- S-01 (User signup) — needs users table
- S-03 (CV upload) — needs cv_files metadata table
- S-05, S-06, S-07 (Job endpoints) — need jobs and evaluations tables
- S-08, S-09 (Job listing) — need user-scoped queries

---

## Phase 1: Project Structure & Dependencies

### Overview
Establish the database module structure, add required dependencies (SQLAlchemy, asyncpg, Alembic, pgvector), and configure Alembic for migration management.

### Changes Required
1. **Create database module structure**:
   - `src/db/` directory (new)
   - `src/db/__init__.py` — export DatabaseSession, engine, init_db()
   - `src/db/models.py` — SQLAlchemy ORM models
   - `src/db/config.py` — database connection settings

2. **Update `src/config/settings.py`**:
   - Add `database_url: str` (from env `AGENTIC_HIRE_DATABASE_URL` or default to `postgresql+asyncpg://user:password@localhost:5432/agentic_hire`)
   - Add `embedding_dimension: int = 1536` (configurable embedding size)
   - Add `postgres_version: str = "17"` (informational)

3. **Update `pyproject.toml`**:
   - Add: `sqlalchemy[asyncio]>=2.0.25`
   - Add: `asyncpg>=0.30.0`
   - Add: `alembic>=1.13.0`
   - Add: `pgvector>=0.3.0`
   - Optionally add to dev: `pytest-mock>=3.14.0`

4. **Initialize Alembic**:
   - Run `alembic init alembic` in project root
   - Configure `alembic/env.py` for async context
   - Set `sqlalchemy.url` in `alembic.ini` to use env var: `postgresql+asyncpg://...`

### Success Criteria
**Automated**:
- `uv run mypy src/db/` — no type errors
- `uv run pytest tests/test_db_config.py -v` — database config loads correctly

**Manual**:
- Alembic can be invoked: `alembic revision --autogenerate -m "message"`
- Dependencies install without conflicts: `uv sync`

---

## Phase 2: Database Models & Alembic

### Overview
Define SQLAlchemy ORM models for users, jobs, cv_embeddings, evaluations, and CV file metadata. Create the initial Alembic migration.

### Changes Required

1. **Define `src/db/models.py`** with:

   ```python
   from sqlalchemy import Column, String, Float, Integer, DateTime, Text, ForeignKey, Index
   from sqlalchemy.ext.declarative import declarative_base
   from sqlalchemy.dialects.postgresql import BYTEA, UUID
   from pgvector.sqlalchemy import Vector
   from datetime import datetime
   import uuid
   
   Base = declarative_base()
   
   class User(Base):
       __tablename__ = "users"
       id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
       email: str = Column(String(255), unique=True, nullable=False, index=True)
       password_hash: str = Column(String(255), nullable=False)
       created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
       updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
   
   class CVFile(Base):
       __tablename__ = "cv_files"
       id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
       user_id: UUID = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
       file_path: str = Column(String(512), nullable=False)  # e.g., /data/cv/user-uuid.pdf
       file_hash: str = Column(String(64), nullable=False)   # SHA256 hash for caching
       ingested_at: datetime = Column(DateTime, default=datetime.utcnow)
       updated_at: datetime = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
   
   class CVEmbedding(Base):
       __tablename__ = "cv_embeddings"
       id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
       user_id: UUID = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
       chunk_text: str = Column(Text, nullable=False)
       embedding: Vector = Column(Vector(EMBEDDING_DIMENSION), nullable=False)  # pgvector column
       created_at: datetime = Column(DateTime, default=datetime.utcnow)
       __table_args__ = (
           Index("ix_cv_embeddings_user_id", "user_id"),
       )
   
   class Job(Base):
       __tablename__ = "jobs"
       id: str = Column(String(255), primary_key=True)  # External job ID from scraper
       user_id: UUID = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
       title: str = Column(String(255), nullable=False)
       company: str = Column(String(255), nullable=False)
       description: str = Column(Text, nullable=True)
       url: str = Column(String(512), nullable=False)
       salary_range: str = Column(String(100), nullable=True)
       discovered_at: datetime = Column(DateTime, default=datetime.utcnow)
       created_at: datetime = Column(DateTime, default=datetime.utcnow)
       __table_args__ = (
           Index("ix_jobs_user_id", "user_id"),
           Index("ix_jobs_url", "url"),
       )
   
   class Evaluation(Base):
       __tablename__ = "evaluations"
       id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
       user_id: UUID = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
       job_id: str = Column(String(255), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
       match_score: float = Column(Float, nullable=False)  # 0.0 to 1.0
       orchestrator_reasoning: str = Column(Text, nullable=True)  # Analysis from Orchestrator
       tailor_summary: str = Column(Text, nullable=True)  # Evaluation from Tailor agent
       evaluated_at: datetime = Column(DateTime, default=datetime.utcnow)
       __table_args__ = (
           Index("ix_evaluations_user_id", "user_id"),
           Index("ix_evaluations_job_id", "job_id"),
       )
   ```

2. **Create initial Alembic migration**:
   - Run: `alembic revision --autogenerate -m "initial_schema_with_pgvector"`
   - Edit `alembic/versions/001_initial_schema_with_pgvector.py` to:
     - Ensure pgvector extension is created: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`
     - Verify all tables and indexes are generated

3. **Create `src/db/__init__.py`**:
   - Export: `Base`, `User`, `CVFile`, `CVEmbedding`, `Job`, `Evaluation`
   - Define async engine factory: `async def create_engine(database_url: str) -> AsyncEngine`
   - Define session maker: `async def get_db_session() -> AsyncGenerator[AsyncSession, None]`

4. **Create `src/db/config.py`**:
   - Database connection helpers
   - Async session management
   - Type hints for ORM models

### Success Criteria
**Automated**:
- `uv run mypy src/db/models.py` — no type errors
- `uv run alembic upgrade head` — migration applies without error
- `uv run pytest tests/test_db_models.py -v` — model instantiation works

**Manual**:
- Connect to PostgreSQL via `psql` and verify all 5 tables exist
- Verify pgvector extension is installed: `SELECT * FROM pg_extension WHERE extname = 'vector'`
- Verify UUID columns are correct type
- Verify indexes exist on user_id and foreign keys

---

## Phase 3: Docker Compose Integration

### Overview
Add a PostgreSQL service to Docker Compose, configure health checks, environment variables, and volume persistence.

### Changes Required

1. **Update `docker-compose.yml`**:
   - Add new `db` service:
     ```yaml
     db:
       image: pgvector/pgvector:pg17
       container_name: agentic-hire-db
       environment:
         POSTGRES_USER: ${POSTGRES_USER:-agentic_hire}
         POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-dev_password}
         POSTGRES_DB: ${POSTGRES_DB:-agentic_hire}
       ports:
         - "5432:5432"
       volumes:
         - postgres_data:/var/lib/postgresql/data
         - ./alembic/versions/:/docker-entrypoint-initdb.d/:ro  # Optional: run migrations on init
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U agentic_hire"]
         interval: 10s
         timeout: 5s
         retries: 5
       networks:
         - agentic-hire-net
     ```

   - Update `api` and `app` services to depend on `db`:
     ```yaml
     depends_on:
       db:
         condition: service_healthy
     ```

   - Update environment variables in `api` and `app`:
     ```yaml
     AGENTIC_HIRE_DATABASE_URL: postgresql+asyncpg://agentic_hire:dev_password@db:5432/agentic_hire
     POSTGRES_USER: agentic_hire
     POSTGRES_PASSWORD: dev_password
     POSTGRES_DB: agentic_hire
     ```

   - Add named volume: `postgres_data:` (for data persistence across restarts)

   - Add network (if not already present): `agentic-hire-net: driver: bridge`

2. **Update `.env.example`**:
   - Add:
     ```
     AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@db:5432/agentic_hire
     POSTGRES_USER=agentic_hire
     POSTGRES_PASSWORD=dev_password
     POSTGRES_DB=agentic_hire
     ```

3. **Update `src/api/main.py` lifespan**:
   - On startup, run Alembic migrations automatically (or rely on Docker init script)
   - Example:
     ```python
     from alembic.config import Config
     from alembic.script import ScriptDirectory
     from alembic.runtime.migration import MigrationContext
     
     async def run_migrations():
         config = Config("alembic.ini")
         script = ScriptDirectory.from_config(config)
         # Run migrations asynchronously
     ```
   - Alternatively, use a separate init container or shell script.

### Success Criteria
**Automated**:
- `docker-compose up` starts PostgreSQL and waits for health check to pass
- `uv run pytest tests/test_docker_db.py -v` — database is reachable from API container

**Manual**:
- `docker ps` shows `agentic-hire-db` container running and healthy
- `docker-compose logs db` shows successful startup
- `psql -h localhost -U agentic_hire -d agentic_hire` connects successfully
- Run `docker-compose down` and verify `postgres_data` volume persists the schema
- Restart with `docker-compose up` and verify tables still exist

---

## Phase 4: Data Access Layer (Repositories)

### Overview
Create an async data access layer (repository pattern) for CRUD operations on users, jobs, CV embeddings, and evaluations. This layer abstracts database logic from FastAPI routes.

### Changes Required

1. **Create `src/db/repositories.py`** with async repository classes:

   ```python
   from sqlalchemy.ext.asyncio import AsyncSession
   from sqlalchemy import select, delete
   from src.db.models import User, CVFile, CVEmbedding, Job, Evaluation, Base
   from uuid import UUID
   from typing import List, Optional
   
   class UserRepository:
       async def create(self, session: AsyncSession, email: str, password_hash: str) -> User
       async def get_by_email(self, session: AsyncSession, email: str) -> Optional[User]
       async def get_by_id(self, session: AsyncSession, user_id: UUID) -> Optional[User]
   
   class CVFileRepository:
       async def create(self, session: AsyncSession, user_id: UUID, file_path: str, file_hash: str) -> CVFile
       async def get_latest_by_user(self, session: AsyncSession, user_id: UUID) -> Optional[CVFile]
       async def update_hash(self, session: AsyncSession, user_id: UUID, new_hash: str) -> None
   
   class CVEmbeddingRepository:
       async def bulk_insert(self, session: AsyncSession, embeddings: List[CVEmbedding]) -> None
       async def search_by_user_and_query(self, session: AsyncSession, user_id: UUID, query_embedding: Vector, limit: int = 5) -> List[CVEmbedding]
       async def delete_by_user(self, session: AsyncSession, user_id: UUID) -> None
   
   class JobRepository:
       async def create_or_update(self, session: AsyncSession, job: Job) -> Job
       async def get_by_id(self, session: AsyncSession, job_id: str) -> Optional[Job]
       async def get_by_user(self, session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Job]
       async def count_by_user(self, session: AsyncSession, user_id: UUID) -> int
   
   class EvaluationRepository:
       async def create(self, session: AsyncSession, evaluation: Evaluation) -> Evaluation
       async def get_by_user(self, session: AsyncSession, user_id: UUID, limit: int = 20, offset: int = 0) -> List[Evaluation]
       async def get_by_job_id(self, session: AsyncSession, job_id: str) -> Optional[Evaluation]
       async def update_scores(self, session: AsyncSession, user_id: UUID, job_id: str, match_score: float, reasoning: str) -> None
   ```

   - All methods use SQLAlchemy async ORM with `await session.execute(...)`
   - Vector search uses pgvector's `<->` operator for cosine similarity
   - Type hints throughout

2. **Create `src/db/database.py`**:
   - Singleton database session factory
   - Async engine initialization
   - Dependency injection helper: `async def get_db() -> AsyncGenerator[AsyncSession, None]`

3. **Tests in `tests/test_repositories.py`**:
   - Mock AsyncSession
   - Test each repository method with assertions
   - Use `@pytest.mark.asyncio` for async tests

### Success Criteria
**Automated**:
- `uv run mypy src/db/repositories.py` — no type errors
- `uv run pytest tests/test_repositories.py -v` — all CRUD operations work

**Manual**:
- Verify vector search returns correct semantic matches (manual query with sample embeddings)

---

## Phase 5: Verification & Seed Data

### Overview
Create seed data script for local development, verify schema with sample data, and confirm pgvector semantic search works.

### Changes Required

1. **Create `scripts/seed_db.py`**:
   ```python
   async def seed_database(session: AsyncSession):
       # Create test users
       user1 = User(email="test1@example.com", password_hash="...")
       # Create test jobs
       job1 = Job(user_id=user1.id, title="Python Engineer", ...)
       # Create sample embeddings
       # Commit to database
   ```
   - Runnable as: `uv run python scripts/seed_db.py`
   - Idempotent (only seeds if database is empty)

2. **Create `tests/test_db_integration.py`**:
   - Fixture: temporary test database (via docker or in-memory)
   - Test vector similarity search: insert sample CV embeddings, query, verify cosine similarity
   - Test user isolation: insert jobs for user A, verify user B cannot see them
   - Test foreign key cascades: delete user, verify all related data is deleted

3. **Create `tests/conftest.py` database fixtures**:
   ```python
   @pytest.fixture
   async def db_session():
       # Create test session, yield, cleanup
   
   @pytest.fixture
   async def test_user(db_session: AsyncSession):
       # Create and return a test user
   
   @pytest.fixture
   async def test_job(db_session: AsyncSession, test_user):
       # Create and return a test job
   ```

4. **Documentation in `context/changes/.../README.md`**:
   - How to run PostgreSQL locally
   - How to run migrations: `alembic upgrade head`
   - How to seed data: `python scripts/seed_db.py`
   - How to query pgvector: examples of vector search syntax
   - Connection string format

### Success Criteria
**Automated**:
- `uv run pytest tests/test_db_integration.py -v` — all integration tests pass
- `uv run mypy scripts/seed_db.py` — no type errors

**Manual**:
- Run seed script: `python scripts/seed_db.py` completes without error
- Verify schema with sample data: `SELECT COUNT(*) FROM users; SELECT COUNT(*) FROM jobs;`
- Test vector search manually with sample CV chunks and verify semantic relevance
- Verify user isolation: insert job for user A, query as user B, confirm no results

---

## Summary

| Phase | Objective | Files Touched | Dependencies | Verification |
|-------|-----------|---------------|--------------|--------------|
| 1 | Setup dependencies & Alembic | pyproject.toml, src/config/settings.py, alembic/ | None | mypy, pytest config tests |
| 2 | Define ORM models & migrations | src/db/models.py, alembic/versions/ | SQLAlchemy, asyncpg, pgvector | mypy, alembic upgrade |
| 3 | Add PostgreSQL to Docker | docker-compose.yml, .env.example, src/api/main.py | Docker image pgvector/pgvector | docker-compose up, health check |
| 4 | Create repository layer | src/db/repositories.py, src/db/database.py, tests/ | AsyncSession, SQLAlchemy ORM | mypy, pytest CRUD tests |
| 5 | Verify & seed data | scripts/seed_db.py, tests/test_db_integration.py, README | conftest.py fixtures | Integration tests, manual seed |

---

## Progress

- [x] 1.1 Create database module structure (src/db/)
- [x] 1.2 Update settings.py with database configuration
- [x] 1.3 Update pyproject.toml with database dependencies
- [x] 1.4 Initialize Alembic
- [ ] 2.1 Define SQLAlchemy ORM models (users, jobs, cv_embeddings, evaluations, cv_files)
- [ ] 2.2 Create Alembic migration with pgvector extension
- [ ] 2.3 Define database session factory and imports
- [ ] 3.1 Add PostgreSQL service to docker-compose.yml
- [ ] 3.2 Update .env.example with database credentials
- [ ] 3.3 Update FastAPI lifespan to handle migrations on startup
- [ ] 4.1 Create async repository classes (UserRepository, JobRepository, etc.)
- [ ] 4.2 Create database session dependency for FastAPI
- [ ] 4.3 Write pytest tests for repositories
- [ ] 5.1 Create seed_db.py script
- [ ] 5.2 Write integration tests for vector search and user isolation
- [ ] 5.3 Create conftest.py with database fixtures
- [ ] 5.4 Document database setup and usage
