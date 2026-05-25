# F-04: CV Vision to pgvector Implementation Plan

---
created: 2026-05-25
change_id: cv-vision-to-pgvector
status: planned
updated: 2026-05-25
---

## Overview

Refactor the CV ingestion pipeline from ChromaDB (local vector store) to PostgreSQL pgvector (persistent multi-user store). Maintains Vision LLM quality and embedding equivalence while enabling user-isolated, persistent storage required for multi-user Phase 2.

**Current State:** CV pipeline (PDF → Vision OCR → embeddings → ChromaDB) works locally but ChromaDB doesn't scale to multi-tenant, doesn't persist across sessions, lacks access control.

**End State:** Same pipeline, embeddings stored in pgvector. Single source of truth is PostgreSQL. ChromaDB retired. Embedding quality verified via cosine similarity regression test on sample CVs.

**Why now:** F-02 (PostgreSQL + pgvector schema) is complete. F-03 (JWT auth) unlocks user isolation. This phase unblocks S-03/S-05/S-06 (CV upload, orchestrator RAG, tailor evaluation).

---

## Current State Analysis

### Existing Architecture

**PDF → Vision LLM Pipeline** (`src/tools/vectordb.py:26-289`)
- `CVVectorManager` orchestrates ingestion
- PDF files converted to base64 images (150 DPI, JPEG quality 85)
- Vision LLM (Claude/GPT-4o) transcribes pages to Markdown with structured headers (#, ##, ###)
- Text chunked via MarkdownHeaderTextSplitter (by headers) + RecursiveCharacterTextSplitter (700 chars, 50 overlap)
- Embeddings generated via OpenAI text-embedding-3-small (1536-dim)
- Stored in ChromaDB at `data/chroma_db/cv_collection`

**Caching Strategy** (`src/tools/vectordb.py:43-44`)
- File hash stored to prevent re-ingestion
- Cache files: `cv_hash.txt` (MD5), `cv_text.md` (text fallback if ChromaDB corrupted)

**Data Models** (`src/db/models.py`)
- User (email, password_hash)
- CVFile (user_id, file_path, file_hash, ingested_at, created_at)
- CVEmbedding (user_id, chunk_text, embedding vector(1536), created_at)

**Agent Integration** (`src/agents/orchestrator.py:22-54`)
- `OrchestratorAgent` calls `CVVectorManager.get_context()` for RAG retrieval
- Wraps Chroma calls in `asyncio.to_thread()` to avoid blocking async

### pgvector Ready State

**Schema exists** (`alembic/versions/001_initial_schema_with_pgvector.py`)
- `cv_embeddings` table with user_id FK, chunk_text, embedding(vector 1536)
- Index on user_id for fast per-user lookups

**Repository layer ready** (`src/db/repositories.py:87-127`)
- `CVEmbeddingRepository` with `bulk_insert()`, `search_by_user_and_query()` (cosine distance), `delete_by_user()`

---

## Key Decisions Locked

| Decision | Choice | Rationale |
|----------|--------|-----------|
| File storage | Filesystem + DB path reference | Simpler than BYTEA; matches current practice |
| Migration strategy | Full cutover + batch migration | Clean; no dual-write complexity |
| Rollback on failure | Fail loudly (no fallback) | Clear error signals; simpler code |
| Regression testing | Cosine similarity on sample CVs | Validates both embedding + store; practical |
| Performance targets | Defer to Phase 2 | MVP doesn't need aggressive optimization |
| Caching strategy | Keep hash-based cache | Avoids redundant Vision LLM calls (expensive) |
| Concurrency model | Stay synchronous (Phase 1) | Single-user demo; async refactor deferred to Phase 2 |
| ChromaDB retirement | Delete after migration + tests | Single source of truth; clean tech debt |
| Chunking strategy | Keep 700-char chunks | No surprises; optimization deferred to Phase 2 |

---

## What We're NOT Doing

- **Async CVVectorManager refactor** — Deferred to Phase 2 when multi-user concurrency is needed
- **Chunk size optimization** — Keeping 700-char chunks; A/B testing deferred to Phase 2
- **Semantic chunking** — Staying with character-based splits
- **Fallback to ChromaDB on error** — Failing loudly instead; simpler recovery path
- **Cloud storage (S3/GCS)** — Using local filesystem for MVP
- **Token-based pricing optimization** — No reduction of embedding calls beyond hash caching

---

## Implementation Approach

1. **Phase 1: Repo & Migration Setup** — Ensure pgvector schema is present, create CVEmbeddingRepository if not, write migration utilities
2. **Phase 2: CVVectorManager Refactor** — Replace ChromaDB with pgvector; keep Vision pipeline unchanged
3. **Phase 3: Agent Integration** — Update orchestrator RAG retrieval to use pgvector instead of Chroma
4. **Phase 4: Regression Testing & Cutover** — Validate embedding quality, batch migrate ChromaDB data (if any), retire ChromaDB, clean up dependencies

---

## Phase 1: Repository & Migration Setup

### Overview

Ensure pgvector database infrastructure is ready and repositories exist for bulk inserts and similarity search. Prepare migration utilities for batch data import.

### Changes Required

#### 1. Verify pgvector Schema & Extension

**File**: `alembic/versions/001_initial_schema_with_pgvector.py`

**Intent**: Ensure pgvector extension is installed and `cv_embeddings` table exists with proper columns and indexes.

**Contract**: 
- PostgreSQL pgvector extension installed and active
- Table: `cv_embeddings` (id UUID, user_id UUID FK, chunk_text TEXT, embedding vector(1536), created_at DATETIME, ix_cv_embeddings_user_id index)
- Schema matches data model in `src/db/models.py:62-80`

#### 2. CVEmbeddingRepository Implementation

**File**: `src/db/repositories.py:87-127`

**Intent**: Provide database layer for bulk inserts and vector similarity search on pgvector.

**Contract**: 
- `CVEmbeddingRepository` class with methods:
  - `bulk_insert(embeddings: list[CVEmbedding])` — Insert many chunks in one transaction
  - `search_by_user_and_query(user_id: UUID, query_embedding: list[float], limit: int) -> list[CVEmbedding]` — Cosine distance search filtered by user_id
  - `delete_by_user(user_id: UUID)` — Cleanup on user deletion

#### 3. Session Management for Async Compatibility

**File**: `src/db/database.py`

**Intent**: Ensure AsyncSession is properly configured for async repository operations in agents.

**Contract**: 
- `get_session_factory()` returns `async_sessionmaker` bound to PostgreSQL engine
- Orchestrator can call `CVEmbeddingRepository` methods via `asyncio.to_thread()` without blocking

### Success Criteria

#### Automated Verification

- PostgreSQL running: `docker-compose ps` shows postgres container
- pgvector extension loaded: `SELECT extname FROM pg_extension WHERE extname = 'vector'` returns 1 row
- Schema migration applies: `uv run alembic upgrade head` completes without error
- CVEmbeddingRepository tests pass: `uv run pytest tests/test_repositories.py::TestCVEmbeddingRepository -v`
- Repository bulk insert works: Insert 10 test embeddings, query returns all 10
- Similarity search works: Query returns expected results ordered by cosine distance

#### Manual Verification

- Connect to PostgreSQL: `psql -U agentic_hire -d agentic_hire_ai` and verify `cv_embeddings` table exists
- Inspect table schema: `\d cv_embeddings` shows id, user_id, chunk_text, embedding columns

---

## Phase 2: CVVectorManager Refactor

### Overview

Refactor `CVVectorManager` to use pgvector instead of ChromaDB. Vision LLM pipeline (PDF → images → OCR → chunks → embeddings) remains unchanged; only the storage backend switches from Chroma to PostgreSQL.

### Changes Required

#### 1. CVVectorManager: Replace ChromaDB with pgvector

**File**: `src/tools/vectordb.py:26-289`

**Intent**: Swap storage backend from ChromaDB to pgvector while keeping Vision pipeline identical.

**Contract**:
- Constructor: `__init__(vision_model, embeddings, db_path, user_id: UUID)` — Now takes `user_id` for multi-user isolation
- `ingest_cv(pdf_path: str) -> dict` — Same signature; same output format
  - Still returns `{"status": "...", "chunks_stored": N, "hash": "..."}`
  - Hash-based caching still works (skip re-ingestion if file unchanged)
  - If file hash exists in DB + matches file on disk, return early
  - Otherwise, proceed with PDF → Vision → chunks → embeddings → pgvector insert
- `get_context(query: str, limit: int = 5) -> str` — Same signature; now queries pgvector instead of Chroma
  - Convert query to embedding via same OpenAI model
  - Cosine distance search in pgvector (user_id filtered)
  - Return concatenated chunk_text as before
- `get_full_resume_text() -> str` — Same; now retrieves from pgvector

**Implementation pattern**:
```python
# OLD: Chroma-based
self.db = Chroma(collection_name="cv_collection", embedding_function=self.embeddings, persist_directory=self.db_path)

# NEW: pgvector-based
self.session = get_session_factory()  # AsyncSession
self.repo = CVEmbeddingRepository(self.session)
self.user_id = user_id  # For multi-user filtering
```

Key changes:
- Remove `from langchain_chroma import Chroma`
- Add imports: `from src.db.repositories import CVEmbeddingRepository`, `from src.db.database import get_session_factory`
- Ingest method: replace `self.db.add_documents()` with `self.repo.bulk_insert()`
- Get context method: replace `self.db.similarity_search()` with `self.repo.search_by_user_and_query()`
- Hash caching logic: store/check hash in database (add `cv_file_hash` column or query CVFile table if exists)

#### 2. Dependencies: Remove ChromaDB, Add pgvector Support

**File**: `pyproject.toml`

**Intent**: Remove Chroma dependency; ensure pgvector and SQLAlchemy are available.

**Contract**:
- Remove: `langchain-chroma>=1.1.0`
- Already present: `pgvector>=0.3.0`, `sqlalchemy[asyncio]>=2.0.25`
- Keep: `langchain-openai`, `pdf2image`, all Vision/embedding dependencies

#### 3. Configuration: Remove ChromaDB References

**File**: `src/config/settings.py`

**Intent**: Remove ChromaDB path configuration; add database connection validation.

**Contract**:
- Remove: Any `chroma_db_path` or similar fields
- Ensure: `database_url` is properly set (required for pgvector access)

### Success Criteria

#### Automated Verification

- Imports work: `uv run python -c "from src.tools.vectordb import CVVectorManager"` succeeds
- CVVectorManager instantiation works: Create instance with test vision_model, embeddings, user_id
- `ingest_cv()` creates pgvector embeddings: Upload test PDF, verify N chunks inserted in `cv_embeddings` table
- `get_context()` retrieves from pgvector: Query "Python experience" returns relevant chunks ordered by similarity
- Hash caching prevents re-ingestion: Ingest same PDF twice, verify Vision LLM called only once

#### Manual Verification

- Query PostgreSQL: `SELECT COUNT(*) FROM cv_embeddings WHERE user_id = '<test-user-id>'` shows embeddings after ingestion
- Vector values are non-null: `SELECT embedding FROM cv_embeddings LIMIT 1` returns a vector

---

## Phase 3: Agent Integration

### Overview

Update `OrchestratorAgent` and any other agents that call `CVVectorManager` to work with the refactored pgvector backend. No changes to agent logic or prompts; just ensure RAG retrieval continues to work.

### Changes Required

#### 1. OrchestratorAgent: Update CVVectorManager Call

**File**: `src/agents/orchestrator.py:22-54`

**Intent**: Ensure orchestrator can instantiate and use the refactored CVVectorManager.

**Contract**:
- On agent initialization, pass `user_id` to CVVectorManager constructor
- RAG retrieval call `cvvector_manager.get_context(query)` works identically (signature unchanged)
- Async wrapping still works: `await asyncio.to_thread(cvvector_manager.get_context, ...)`

#### 2. AgentFactory: Pass User Context

**File**: `src/agents/agents.py:31-40`

**Intent**: Ensure CVVectorManager is initialized with user_id from state.

**Contract**:
- Factory method creates CVVectorManager with `user_id` from `state["user_id"]` (or similar context)
- Or pass user_id as part of agent invocation

### Success Criteria

#### Automated Verification

- OrchestratorAgent instantiation works: Create agent with mock CVVectorManager
- RAG retrieval call works: `orchestrator.invoke(state)` succeeds and calls `get_context()`
- State flow unchanged: Agent output format and structure identical to before

#### Manual Verification

- End-to-end test: Run agent with sample CV uploaded to pgvector, verify job matching works
- No regressions: Existing agent tests still pass

---

## Phase 4: Regression Testing & Cutover

### Overview

Validate that pgvector embeddings match ChromaDB quality via cosine similarity tests on sample CVs. If validated, batch migrate any existing data and retire ChromaDB.

### Changes Required

#### 1. Regression Test: Sample CV Similarity Validation

**File**: `tests/test_cv_vision_pgvector_migration.py` (new)

**Intent**: Verify that embeddings generated and stored in pgvector are equivalent to ChromaDB for the same input.

**Contract**:
- Test data: 2-3 representative sample CVs (e.g., software engineer, product manager, data scientist roles)
- Process:
  1. Ingest same CV into BOTH ChromaDB (old) and pgvector (new) via identical Vision LLM pipeline
  2. For each test query ("Python experience", "Project management", "Data analysis"), run similarity search on both
  3. Compare top-5 results: cosine similarity scores should match within ±1% (numerical precision tolerance)
  4. Assert no embedding drift (same embeddings produced)
- Output: Pass/fail report; if fail, show which queries diverged and by how much

#### 2. Batch Migration (If Needed)

**File**: `scripts/migrate_chroma_to_pgvector.py` (new, optional for MVP)

**Intent**: If ChromaDB contains user data, transfer embeddings to pgvector while preserving metadata.

**Contract**:
- Read all documents from ChromaDB collection
- Extract chunk_text and metadata (user_id, created_at if stored)
- Batch insert into pgvector via CVEmbeddingRepository
- Verify row counts match source

**Note**: For single-user MVP, ChromaDB likely empty; this is placeholder for Phase 2 multi-user migration.

#### 3. ChromaDB Removal

**File**: `src/tools/vectordb.py`, `src/config/settings.py`, `pyproject.toml`

**Intent**: Delete ChromaDB code, config, and data once pgvector validated.

**Contract**:
- Remove `data/chroma_db/` directory (and `.gitignore` entry if present)
- Remove any ChromaDB-specific environment variables or config
- Keep hash caching logic but store hashes in database (CVFile table)
- Dependencies already removed in Phase 2

### Success Criteria

#### Automated Verification

- Regression test passes: `uv run pytest tests/test_cv_vision_pgvector_migration.py -v` — all sample CVs show ≤1% cosine similarity difference
- ChromaDB removal: `grep -r "chroma\|Chroma" src/` returns no results (except comments/docstrings mentioning old system)
- Dependencies resolved: `uv sync` succeeds; pyproject.toml has no `langchain-chroma`
- Full test suite passes: `uv run pytest tests/ -v` (all tests still green with pgvector backend)

#### Manual Verification

- Verify pgvector data integrity: `SELECT COUNT(*) FROM cv_embeddings` matches expected chunk count after ingestion
- Manual similarity search: Query pgvector directly and verify results are semantically relevant
- No data loss: All embeddings present; none corrupted

---

## Testing Strategy

### Unit Tests

- `CVVectorManager` with pgvector backend: Test ingest, get_context, get_full_resume_text
- `CVEmbeddingRepository`: Test bulk_insert, search_by_user_and_query, delete_by_user
- Hash caching: Test that unchanged files skip re-ingestion

### Integration Tests

- End-to-end ingest + retrieve: Upload PDF → store in pgvector → query → verify results
- Agent RAG flow: OrchestratorAgent calls CVVectorManager → gets context → uses in scoring
- Multi-user isolation: Two users upload CVs; searches are filtered by user_id; no leakage

### Regression Tests

- Sample CV cosine similarity: Embeddings match ±1% between old (simulated) and new
- Existing CV pipeline quality: Vision LLM output unchanged; chunking unchanged; embeddings match prior

---

## Performance Considerations

- **Ingestion latency**: Expect ~30-60s per CV (unchanged from ChromaDB; limited by Vision LLM call time)
- **Similarity search**: Cosine distance with pgvector index ~50-200ms; acceptable for MVP
- **Optimization deferred**: Phase 2 may tune chunk size, embedding model, or add caching layers

---

## Migration & Rollback

**Migration Path** (Phase 1 → Phase 2 → Phase 3 → Phase 4):
1. Set up pgvector schema + repository
2. Refactor CVVectorManager to pgvector backend
3. Update agents to use refactored manager
4. Run regression tests; if pass, retire ChromaDB

**Rollback** (if regression tests fail):
- Full cutover strategy means no fallback to ChromaDB
- If issues found: Fix them (embedding drift, query logic, etc.), re-test, retry cutover
- No "revert to old system" option in Phase 1; code is the truth

---

## References

- Current implementation: `src/tools/vectordb.py:26-289`
- Data models: `src/db/models.py:26-80`
- Repository patterns: `src/db/repositories.py:87-127`
- Agent integration: `src/agents/orchestrator.py:22-54`
- Schema: `alembic/versions/001_initial_schema_with_pgvector.py:52-63`
- Roadmap: F-04, F-05 (Docker hardening); unlocks S-03, S-05, S-06

---

## Progress

### Phase 1: Repository & Migration Setup

#### Automated

- [x] 1.1 Verify pgvector schema and extension are present
- [x] 1.2 CVEmbeddingRepository with bulk_insert, search_by_user_and_query, delete_by_user
- [x] 1.3 AsyncSession configured for repository operations
- [x] 1.4 Repository tests pass (bulk insert, similarity search, user filtering)

#### Manual

- [x] 1.5 PostgreSQL connection verified; cv_embeddings table inspected

### Phase 2: CVVectorManager Refactor

#### Automated

- [x] 2.1 CVVectorManager replaced ChromaDB with pgvector calls
- [x] 2.2 Hash-based caching logic adapted for database
- [x] 2.3 Ingest pipeline works end-to-end (PDF → pgvector)
- [x] 2.4 get_context retrieves embeddings from pgvector
- [x] 2.5 ChromaDB dependency removed from pyproject.toml
- [x] 2.6 Migration tests pass for new implementation

#### Manual

- [x] 2.7 Manual ingest: Upload test PDF, verify embeddings in PostgreSQL

### Phase 3: Agent Integration

#### Automated

- [x] 3.1 OrchestratorAgent works with refactored CVVectorManager
- [x] 3.2 User ID passed through agent factory
- [x] 3.3 Agent tests pass (no regression in inference)
- [x] 3.4 Async wrapping still functional (to_thread calls)

#### Manual

- [x] 3.5 End-to-end agent test: CV upload → orchestrator → recommendations

### Phase 4: Regression Testing & Cutover

#### Automated

- [x] 4.1 Regression test: Sample CVs show cosine similarity ≤1% diff
- [x] 4.2 ChromaDB code/config removed from codebase
- [x] 4.3 Full test suite passes with pgvector backend
- [x] 4.4 Batch migration (if needed) tested

#### Manual

- [x] 4.5 PostgreSQL data integrity verified (row counts, vector values)
- [x] 4.6 Manual similarity search: Query pgvector, verify relevance
