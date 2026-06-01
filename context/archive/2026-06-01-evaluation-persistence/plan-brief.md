# Evaluation Persistence — Plan Brief

> Full plan: `context/changes/evaluation-persistence/plan.md`

## What & Why

After the LangGraph workflow completes, the API returns match scores and tailor summaries in the response JSON — but never writes them to the `evaluations` table. The "Discovered Jobs" frontend page does a LEFT OUTER JOIN against that table and always gets `null` scores. This change closes the write gap so scores appear in the UI from the database.

## Starting Point

The `Evaluation` model, `EvaluationRepository`, and the frontend score display logic all exist. Both workflow endpoints already have a `session: AsyncSession` dependency injected. The only missing piece is the loop that calls `EvaluationRepository.upsert()` after `graph.ainvoke()` / `graph.astream()` completes. The `evaluations` table also has no unique constraint on `(user_id, job_id)`, so duplicate rows would accumulate on repeat runs without one.

## Desired End State

After a workflow run, every shortlisted job has a row in `evaluations` with `match_score`, `orchestrator_reasoning`, and `tailor_summary` populated. Re-running updates existing rows. The frontend "Discovered Jobs" page shows color-coded match score badges instead of "—". If DB persistence fails, the API still returns the workflow result with the scores in the response body.

## Key Decisions Made

| Decision | Choice | Why (1 sentence) | Source |
|---|---|---|---|
| Duplicate handling | Upsert via `ON CONFLICT DO UPDATE` | Re-running workflow must refresh scores, not append stale rows | Plan |
| Persistence failure posture | Log error, still return response | Scores are already in the API JSON; a DB blip shouldn't break the UX | Plan |
| Streaming endpoint | Persist in both endpoints | Streamlit UI uses the streaming path; fixing only sync would leave scores missing for most users | Plan |
| Tests | Unit tests with mocked session | Guards against accidental removal of the persistence block in future refactors | Plan |

## Scope

**In scope:**
- `UniqueConstraint(user_id, job_id)` on `evaluations` + Alembic migration
- `EvaluationRepository.upsert()` using PostgreSQL `ON CONFLICT DO UPDATE`
- Persistence loop in non-streaming endpoint (`search_jobs_workflow`)
- Persistence loop in streaming endpoint (`run_graph()` inner function)
- Unit tests: upsert called per job + error recovery behavior

**Out of scope:**
- Persisting rejected jobs' evaluations
- Changing API response schema
- Observability / tracing for the persistence step
- Re-trigger endpoint for past runs

## Architecture / Approach

Both endpoints already have `session` available. The non-streaming endpoint adds a `try/except` block after line 152 (graph results extracted). The streaming endpoint adds the same block inside the `run_graph()` inner coroutine after `graph.astream()` finishes — `session` is accessible via closure since it's set before `asyncio.create_task(run_graph())`. A PostgreSQL `INSERT ... ON CONFLICT ON CONSTRAINT uq_evaluations_user_job DO UPDATE` handles idempotent writes without two round-trips.

## Phases at a Glance

| Phase | What it delivers | Key risk |
|---|---|---|
| 1. Schema + upsert | Unique constraint in model + migration + `EvaluationRepository.upsert()` | Existing duplicate rows block migration — needs manual dedup first |
| 2. Persistence in both endpoints | Write path wired in sync + streaming routes | Streaming closure access to `session` — verified safe by async task/closure semantics |
| 3. Unit tests | Regression guard for persistence + error recovery | None significant |

**Prerequisites:** DB running (`docker-compose up`); existing `evaluations` table must not have duplicate `(user_id, job_id)` rows before running Phase 1 migration.  
**Estimated effort:** ~1 session across 3 phases

## Open Risks & Assumptions

- If a dev DB already has duplicate `(user_id, job_id)` rows in `evaluations`, the migration will fail. Resolution: dedup query in Migration Notes section of the full plan.
- The `applications` dict key `"founded_job_offer"` is assumed stable (observed in `src/api/routes/workflows.py:165` and `388`). If Tailor changes its output key, `tailor_summary` will silently be `None`.

## Success Criteria (Summary)

- `SELECT * FROM evaluations` shows rows with non-null `match_score` after a workflow run
- Frontend "Discovered Jobs" page shows color-coded score badges
- Re-running the workflow updates rows rather than duplicating them
