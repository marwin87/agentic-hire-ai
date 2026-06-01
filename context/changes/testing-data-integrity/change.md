---
change_id: testing-data-integrity
title: Data integrity integration tests — evaluation persistence and user isolation
status: implemented
created: 2026-06-01
updated: 2026-06-01
archived_at: null
---

## Notes

Open a change folder for rollout Phase 1 of context/foundation/test-plan.md: "Data integrity".
  Risks covered: #1 (evaluation persistence write fails silently), #2 (user data isolation missing — cross-user row
  access).
  Test types planned: integration (real async DB session, two-user fixture).
  Risk response intent:
  - Risk #1: prove that after workflow completes, every shortlisted job has a non-null match_score in the DB that
  survives a page reload; do not assert only the API response JSON. 
  - Risk #2: prove that a request authenticated as user A cannot retrieve or modify user B's jobs, CVs, or evaluations;
  do not test only single-user happy paths.
  After creating the folder, suggest running /10x-research next.
