---
change_id: postgresql-pgvector-setup
title: PostgreSQL + pgvector schema setup
created: 2026-05-25
status: archived
archived_at: 2026-05-25T22:30:14Z
updated: 2026-05-25
phase_1_completed: true
---

# Change: PostgreSQL + pgvector setup

Foundation item F-02. Sets up the database layer for multi-user support and semantic search with pgvector.

## References

- **Roadmap**: context/foundation/roadmap.md (F-02 section)
- **PRD**: context/foundation/prd.md (sections: Scope of Change, Data Schema & Persistence)
- **Related Foundation**: F-01 (fastapi-scaffold) — completed

## Unlock

This change unblocks:
- S-01 (User signup — needs users table)
- S-03 (CV upload — needs CV storage design)
- S-05, S-06, S-07 (Job results — need jobs and evaluations tables)
- S-08, S-09 (Job listing endpoints — need user-scoped queries)

## Key Dependencies & Unknowns

- Q2 (CV file storage): Filesystem or bytea? This affects schema design and downstream implementation.

## Success Criteria

- PostgreSQL container runs locally via Docker
- pgvector extension installed and configured
- Schema created: users, jobs, cv_embeddings, evaluations tables
- Foreign keys enforce user_id isolation
- Vector similarity search verified
- Docker Compose integration complete
