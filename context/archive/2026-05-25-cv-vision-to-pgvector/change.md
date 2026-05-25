---
change_id: cv-vision-to-pgvector
status: archived
archived_at: 2026-05-25T13:32:02Z
created: 2026-05-25
updated: 2026-05-25
---

# F-04: CV Vision to pgvector

Refactor CV ingestion pipeline from ChromaDB to PostgreSQL pgvector, maintaining Vision LLM quality and adding user-isolated persistent storage.

**Outcome**: CV embeddings stored in pgvector. Pipeline: PDF → Vision LLM OCR → embeddings → pgvector inserts. Regression test validates embedding quality matches prior system.

**Depends on**: F-02 (PostgreSQL + pgvector schema ✓)

**Unlocks**: S-03 (CV upload), S-05 (Orchestrator context), S-06 (Tailor context)

**Key unknown**: CV file storage method (filesystem path vs. Postgres bytea)
