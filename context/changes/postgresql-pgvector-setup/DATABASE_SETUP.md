# PostgreSQL + pgvector Database Setup Guide

This guide covers setting up and using the PostgreSQL database with pgvector support for the AgenticHire AI multi-user job matching system.

## Quick Start

### Prerequisites
- Docker and Docker Compose (recommended for local development)
- PostgreSQL 17 with pgvector extension (or use Docker)
- Python 3.13+

### Local Setup (Docker Recommended)

1. **Start PostgreSQL with pgvector**:
   ```bash
   docker-compose up db
   ```

   This starts a PostgreSQL 17 container with pgvector pre-installed:
   - Host: `localhost`
   - Port: `5432`
   - Database: `agentic_hire`
   - User: `agentic_hire`
   - Password: `dev_password` (from `.env`)

2. **Run migrations**:
   ```bash
   # With the database running, apply all migrations
   alembic upgrade head
   ```

   This creates all tables and indexes. The initial migration (`001_initial_schema_with_pgvector.py`) sets up:
   - `users` table (UUID primary key, unique email)
   - `cv_files` table (stores CV file metadata and hash for caching)
   - `cv_embeddings` table (pgvector column for semantic search)
   - `jobs` table (job postings per user)
   - `evaluations` table (match scores per job-user pair)

3. **Seed test data (optional)**:
   ```bash
   uv run python scripts/seed_db.py
   ```

   This creates test users (alice@example.com, bob@example.com), sample jobs, and evaluations for local testing.

4. **Verify schema**:
   ```bash
   # Connect to database
   psql -h localhost -U agentic_hire -d agentic_hire

   # Check tables
   \dt

   # Check pgvector extension
   SELECT * FROM pg_extension WHERE extname = 'vector';

   # Count test data
   SELECT COUNT(*) FROM users;
   SELECT COUNT(*) FROM jobs;
   SELECT COUNT(*) FROM evaluations;
   ```

## Connection String Format

```
postgresql+asyncpg://username:password@host:port/database

# Example (localhost, Docker)
postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire

# Example (Docker Compose, from another service)
postgresql+asyncpg://agentic_hire:dev_password@db:5432/agentic_hire
```

## Environment Variables

Set these in `.env` (copy from `.env.example`):

```bash
# Database connection
AGENTIC_HIRE_DATABASE_URL=postgresql+asyncpg://agentic_hire:dev_password@localhost:5432/agentic_hire

# PostgreSQL credentials (for Docker Compose)
POSTGRES_USER=agentic_hire
POSTGRES_PASSWORD=dev_password
POSTGRES_DB=agentic_hire

# Optional: embedding dimension (default 1536 for OpenRouter)
AGENTIC_HIRE_EMBEDDING_DIMENSION=1536
```

## Data Model Overview

### Users
Represents a user in the system. Stores authentication credentials and timestamps.

```sql
SELECT * FROM users;
-- id (UUID), email (unique), password_hash, created_at, updated_at
```

### CV Files
Stores metadata for user CVs. File hash enables caching: if hash unchanged, skip re-ingestion.

```sql
SELECT * FROM cv_files WHERE user_id = 'some-uuid' ORDER BY updated_at DESC LIMIT 1;
-- id (UUID), user_id (FK), file_path, file_hash, ingested_at, updated_at
```

### CV Embeddings
Semantic embeddings of CV chunks. Uses pgvector for vector similarity search.

```sql
-- Semantic search: find embeddings most similar to a query vector
SELECT id, chunk_text, embedding <-> query_vector AS distance
FROM cv_embeddings
WHERE user_id = 'some-uuid'
ORDER BY distance
LIMIT 5;
-- Cosine distance: lower values = more similar
```

### Jobs
Job postings associated with users. Enables multi-user isolation: each user has their own job list.

```sql
SELECT * FROM jobs WHERE user_id = 'some-uuid' ORDER BY discovered_at DESC LIMIT 20;
-- id (String, external job ID), user_id (FK), title, company, description, url, salary_range, ...
```

### Evaluations
Match scores linking users to jobs. Enables users to have independent evaluations of the same job posting.

```sql
SELECT * FROM evaluations WHERE user_id = 'some-uuid' ORDER BY evaluated_at DESC;
-- id (UUID), user_id (FK), job_id (FK), match_score (0.0-1.0), reasoning, tailor_summary, evaluated_at
```

## User Isolation

The database enforces multi-user isolation through foreign key constraints:

1. **Job isolation**: `jobs.user_id` uniquely identifies jobs for a user
   - User A cannot see User B's jobs
   - Query: `SELECT * FROM jobs WHERE user_id = ?`

2. **CV embedding isolation**: `cv_embeddings.user_id` ensures embeddings are private
   - Vector search always filters by `user_id`
   - Query: `SELECT * FROM cv_embeddings WHERE user_id = ? ORDER BY embedding <-> query_vector`

3. **Evaluation isolation**: `evaluations.user_id` keeps scores private
   - User A only sees their own match scores
   - Query: `SELECT * FROM evaluations WHERE user_id = ?`

4. **Cascading deletes**: If a user is deleted, all related data is automatically removed
   - CV files, embeddings, jobs, and evaluations cascade delete
   - Foreign key constraint: `ON DELETE CASCADE`

## Repository Layer Usage

All database interactions go through async repository classes in `src/db/repositories.py`:

### UserRepository
```python
user = await UserRepository.create(session, email="user@example.com", password_hash=hash)
user = await UserRepository.get_by_email(session, "user@example.com")
user = await UserRepository.get_by_id(session, user_id)
```

### JobRepository
```python
job = await JobRepository.create_or_update(session, job_obj)
jobs = await JobRepository.get_by_user(session, user_id, limit=20, offset=0)
count = await JobRepository.count_by_user(session, user_id)
```

### CVEmbeddingRepository
```python
# Vector similarity search (returns top-k semantically similar chunks)
embeddings = await CVEmbeddingRepository.search_by_user_and_query(
    session, user_id, query_embedding=[0.1, 0.2, ...], limit=5
)

# Bulk insert for batch ingestion
await CVEmbeddingRepository.bulk_insert(session, [embedding1, embedding2, ...])

# Clean up when re-ingesting
await CVEmbeddingRepository.delete_by_user(session, user_id)
```

### EvaluationRepository
```python
evaluation = await EvaluationRepository.create(session, evaluation_obj)
evaluations = await EvaluationRepository.get_by_user(session, user_id)
await EvaluationRepository.update_scores(
    session, user_id, job_id, match_score=0.85, reasoning="..."
)
```

## Alembic Migrations

Migrations are version-controlled and reversible:

```bash
# View migration status
alembic current
alembic history

# Apply all migrations
alembic upgrade head

# Apply up to specific version
alembic upgrade 001

# Rollback one version
alembic downgrade -1
```

### Creating New Migrations

After modifying `src/db/models.py`, create a new migration:

```bash
# Auto-generate migration (detects schema changes)
alembic revision --autogenerate -m "add_new_column_to_jobs"

# Or write manually for complex operations
alembic revision -m "custom_migration"
```

Edit `alembic/versions/NNN_migration_name.py` and implement `upgrade()` and `downgrade()` functions.

## pgvector Operations

### Vector Search Syntax

The database uses pgvector's `<->` operator for cosine distance:

```sql
-- Find 5 most similar embeddings to a query vector
SELECT id, chunk_text, embedding <-> '[0.1, 0.2, ...]'::vector AS distance
FROM cv_embeddings
WHERE user_id = 'user-uuid'
ORDER BY distance
LIMIT 5;

-- Distance values: 0.0 = identical, 2.0 = most different
```

### Embedding Dimension

Default: 1536 (OpenRouter/OpenAI standard)
Configure via `AGENTIC_HIRE_EMBEDDING_DIMENSION` or `AppConfig.embedding_dimension`.

All embeddings must be same dimension — mixing breaks queries.

## Testing

### Run Integration Tests

```bash
# All database tests (conftest.py fixtures + test_db_integration.py)
uv run pytest tests/test_db_integration.py -v

# Repository unit tests (mocked AsyncSession)
uv run pytest tests/test_repositories.py -v

# Model instantiation tests
uv run pytest tests/test_db_models.py -v

# Config tests
uv run pytest tests/test_db_config.py -v
```

### Test Data

Use fixtures from `tests/conftest.py`:

```python
@pytest_asyncio.fixture
async def test_user(db_session):
    """Provides a test User object"""

@pytest_asyncio.fixture
async def test_job(test_user):
    """Provides a Job linked to test_user"""

@pytest_asyncio.fixture
async def test_cv_embeddings(test_user):
    """Provides sample CV embeddings for vector search tests"""
```

## Troubleshooting

### Connection Refused
```
psycopg2.OperationalError: could not connect to server
```
- Check Docker container is running: `docker ps | grep postgres`
- Verify `AGENTIC_HIRE_DATABASE_URL` is correct
- Check network: if using Docker Compose, use service name `db` not `localhost`

### pgvector Extension Not Found
```
psycopg2.ProgrammingError: type "vector" does not exist
```
- Extension not loaded: run migration `alembic upgrade head`
- Verify: `SELECT * FROM pg_extension WHERE extname = 'vector'`

### Vector Dimension Mismatch
```
ERROR: vector dimension 1536 does not match column dimension 384
```
- Embedding dimension changed mid-project
- Re-ingest embeddings with new dimension or migrate old data

### Unique Constraint Violation
```
IntegrityError: (psycopg2.IntegrityError) duplicate key value
```
- Duplicate email: `users.email` is unique
- Duplicate job: `jobs.id` is primary key (external job ID)
- Check existing data: `SELECT * FROM users WHERE email = '...'`

## Performance Tuning

### Indexes
Created by migrations:
- `users.email` — fast email lookup
- `jobs.user_id` — fast user job queries
- `cv_embeddings.user_id` — fast embedding lookup
- `evaluations.user_id, evaluations.job_id` — fast evaluation lookups

Add custom indexes for heavy queries:
```sql
CREATE INDEX ix_cv_embeddings_created_at ON cv_embeddings(created_at);
CREATE INDEX ix_jobs_created_at ON jobs(created_at DESC);
```

### Connection Pool
Configure in `src/db/config.py`:
- **Production**: `QueuePool(max_overflow=10, pool_size=20)`
- **Tests**: `NullPool` (no connection reuse)
- **Development**: `QueuePool(max_overflow=10, pool_size=5)`

### Vector Search Performance
- HNSW indexes coming in pgvector 1.0 (future enhancement)
- Current: sequential scan with distance computation
- Optimize by filtering user_id first, then computing distance

## Backup & Restore

### Backup
```bash
# Full database dump
pg_dump -h localhost -U agentic_hire agentic_hire > backup.sql

# Compressed backup
pg_dump -h localhost -U agentic_hire agentic_hire | gzip > backup.sql.gz
```

### Restore
```bash
# From dump
psql -h localhost -U agentic_hire agentic_hire < backup.sql

# From compressed backup
gunzip -c backup.sql.gz | psql -h localhost -U agentic_hire agentic_hire
```

### Docker Compose Volumes
Persistent data stored in `postgres_data` named volume:
```bash
# Persist across `docker-compose down`
docker volume ls | grep postgres_data

# Remove all data (careful!)
docker volume rm agentic-hire-ai_postgres_data
```

## Next Steps

1. **Implement S-01 (User signup)** — uses UserRepository.create()
2. **Implement S-03 (CV upload)** — uses CVFileRepository, CVEmbeddingRepository
3. **Implement S-05+ (Job endpoints)** — use JobRepository, EvaluationRepository
4. **Implement LangGraph integration** — pass session factory to agents for database operations

## References

- **SQLAlchemy Async ORM**: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **pgvector**: https://github.com/pgvector/pgvector
- **Alembic**: https://alembic.sqlalchemy.org/
- **AsyncPG**: https://github.com/MagicStack/asyncpg
