# F-04: CV Vision to pgvector — Plan Brief

---
**Change ID:** cv-vision-to-pgvector  
**Status:** planned  
**Effort:** 4 phases, ~2–3 weeks (depending on manual testing + batch migration scope)  
**Unlocks:** S-03 (CV upload), S-05 (orchestrator RAG), S-06 (tailor evaluation), Phase 2 multi-user  
**Dependencies:** F-02 (PostgreSQL + pgvector schema) ✓, F-03 (JWT auth + user isolation) ✓

---

## The Problem

**Current State:** CV ingestion works locally (PDF → Vision LLM OCR → embeddings → ChromaDB) but ChromaDB:
- Does not persist across sessions (in-memory/local only)
- Cannot scale to multi-tenant (no access control, no per-user isolation)
- Lacks operational guarantees (no data recovery, no transaction semantics)

**Why It Matters:**
- Phase 2 requires persistent multi-user CV storage
- Agent RAG must be user-isolated (one user's CV irrelevant to another)
- Orchestrator needs fast similarity search across persistent embeddings

---

## The Solution

**Refactor CV pipeline to pgvector** (PostgreSQL vector extension):
- Keep Vision LLM OCR pipeline unchanged (same embeddings quality)
- Replace ChromaDB with pgvector for storage + similarity search
- Add `user_id` filtering to all vector operations (multi-user safety)
- Retire ChromaDB once pgvector validated (single source of truth)

**End State:**
- Same embedding quality, same chunking (700 chars), same retrieval accuracy
- Persistent storage in PostgreSQL with transaction guarantees
- User-isolated queries via foreign key filtering
- Regression-tested equivalence (cosine similarity within ±1%)
- Ready for Phase 2 multi-user orchestration

---

## Key Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **File storage** | Filesystem + DB path ref | Simpler than BYTEA; aligns with current practice |
| **Migration** | Full cutover (no dual-write) | Cleaner; avoids complex sync logic |
| **Rollback strategy** | Fail loudly (no fallback) | Clear error signals; simpler recovery |
| **Testing approach** | Cosine similarity on sample CVs | Validates both embedding + storage |
| **Performance targets** | Defer to Phase 2 | MVP doesn't need aggressive tuning |
| **Caching** | Keep hash-based caching | Avoids redundant Vision LLM calls (expensive) |
| **Concurrency** | Stay synchronous (Phase 1) | Single-user demo; async refactor in Phase 2 |
| **ChromaDB cleanup** | Delete after migration + tests | Single source of truth; no legacy dual reads |

---

## Phases at a Glance

### Phase 1: Repository & Migration Setup
**Goal:** Ensure pgvector infrastructure ready for use.

- Verify pgvector extension installed + `cv_embeddings` table exists
- Implement `CVEmbeddingRepository` (bulk insert, cosine search, user filtering)
- Configure AsyncSession for async repository operations
- **Success:** Repository tests pass; PostgreSQL queries work

### Phase 2: CVVectorManager Refactor
**Goal:** Swap storage backend from ChromaDB to pgvector.

- Replace `Chroma()` with pgvector calls in `CVVectorManager`
- Adapt hash caching logic (store hashes in database)
- Add `user_id` parameter to constructor (multi-user isolation)
- Remove `langchain-chroma` dependency
- **Success:** Ingest PDF → embeddings stored in pgvector; get_context retrieves via cosine search

### Phase 3: Agent Integration
**Goal:** Wire refactored manager into OrchestratorAgent.

- Update `OrchestratorAgent` to pass `user_id` to CVVectorManager
- Ensure RAG retrieval call signature unchanged (backward compatible)
- Verify async wrapping still works (`asyncio.to_thread`)
- **Success:** Agent tests pass; end-to-end flow works

### Phase 4: Regression Testing & Cutover
**Goal:** Validate quality + retire ChromaDB.

- Regression test: Sample CVs show embedding equivalence (≤1% cosine diff)
- Batch migrate ChromaDB data (if any exists)
- Delete ChromaDB code, config, and data files
- Full test suite passes
- **Success:** pgvector is single source of truth; ChromaDB gone

---

## What We're NOT Doing

- Async CVVectorManager refactor (Phase 2 feature)
- Chunk size optimization or semantic chunking (Phase 2 investigation)
- Fallback to ChromaDB on error (failing loudly instead)
- Cloud storage (S3/GCS); staying filesystem-local
- Token-based pricing optimization

---

## Technical Scope

### Files Changed per Phase

**Phase 1:**
- Verify: `alembic/versions/001_initial_schema_with_pgvector.py`
- Implement: `src/db/repositories.py` (CVEmbeddingRepository methods)
- Ensure: `src/db/database.py` (AsyncSession config)

**Phase 2:**
- Refactor: `src/tools/vectordb.py` (CVVectorManager)
- Remove: `langchain-chroma` from `pyproject.toml`
- Remove: ChromaDB references from `src/config/settings.py`

**Phase 3:**
- Update: `src/agents/orchestrator.py` (user_id passing)
- Update: `src/agents/agents.py` (factory method)

**Phase 4:**
- New: `tests/test_cv_vision_pgvector_migration.py` (regression suite)
- Optional: `scripts/migrate_chroma_to_pgvector.py` (batch migration)
- Delete: `data/chroma_db/` directory
- Remove: ChromaDB imports, config, and cache files

### Testing Strategy

- **Unit:** CVVectorManager methods, CVEmbeddingRepository CRUD, hash caching
- **Integration:** End-to-end PDF ingest → pgvector → retrieval
- **Regression:** Sample CVs (software engineer, PM, data scientist); query equivalence ≤1% cosine diff
- **Multi-user:** Verify user_id filtering prevents cross-user leakage

### Performance Baseline (MVP)

- Ingestion: ~30–60s per CV (Vision LLM limited, unchanged)
- Similarity search: ~50–200ms (pgvector cosine index)
- No aggressive tuning planned for Phase 1

---

## Risk & Mitigation

| Risk | Mitigation |
|------|-----------|
| Embedding drift (pgvector vs. ChromaDB) | Regression test on sample CVs; ≤1% tolerance |
| Multi-user isolation bugs (user_id leakage) | Filter all queries by user_id; test with multiple users |
| Hash caching complexity (moving to database) | Leverage existing CVFile table; test caching logic separately |
| Slow cutover (Vision LLM bottleneck) | Expected and acceptable; defer optimization to Phase 2 |
| ChromaDB data loss (if any exists) | Batch migration script + verify row counts before delete |

---

## Success Criteria

**All phases complete when:**
1. pgvector schema verified + CVEmbeddingRepository tested
2. CVVectorManager works with pgvector backend + ingest/retrieve tested
3. OrchestratorAgent integrated + end-to-end tests pass
4. Regression tests show embedding equivalence (≤1% cosine diff)
5. ChromaDB removed; no dual-write/read; full test suite green

---

## Next Steps

1. Confirm plan + brief alignment
2. Run `/10x-implement cv-vision-to-pgvector phase 1` to begin Phase 1
3. After Phase 1 validation, proceed through Phases 2–4 (can pause between phases for review)
4. Post-Phase 4: Archive this change with `/10x-archive cv-vision-to-pgvector` and unblock S-03/S-05/S-06
