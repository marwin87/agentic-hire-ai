# User Job List — Plan Brief

> Full plan: `context/changes/user-job-list/plan.md`
> Roadmap: S-08 in `context/foundation/roadmap.md` (FR-007)

## What & Why

Build a `GET /api/jobs` endpoint that returns the authenticated user's discovered job listings with pagination. This is the backbone of the results dashboard (Stream B) — users need to view their complete job history (both evaluated and unevaluated) before the evaluations view (S-09) makes sense.

## Starting Point

- FastAPI server and JWT authentication are production-ready (F-01, F-03 archived)
- PostgreSQL + jobs table exists with user_id FK for multi-user isolation (F-02 archived)
- S-06 unified workflow endpoint populates jobs as it runs; Evaluation table stores optional match_scores
- JobRepository has `get_by_user()` for pagination; no LEFT OUTER JOIN method yet

## Desired End State

A working endpoint `GET /api/jobs?page=1&page_size=10` that:
- Returns paginated list of the authenticated user's jobs (default 10 per page, max 50)
- Each job includes: id, title, company, url, match_score (nullable if not yet evaluated)
- Response always includes pagination metadata: page, total_count, page_size
- Sorting is fixed to discovered_at DESC (newest first)
- Invalid pagination parameters are clamped to valid range (no 400 errors)
- Multi-user isolation is enforced: user only sees their own jobs
- OpenAPI documentation auto-generated

## Key Decisions Made

| Decision | Choice | Why | Source |
|----------|--------|-----|--------|
| Pagination response | page, total_count, page_size | Standard REST; matches front-end expectations for "X of Y" pagination controls | Plan |
| Default page size | 10 items, max 50 | Conservative for MVP; avoids bloated responses while allowing power users to request more | Plan |
| Job fields | id, title, company, url, match_score | Minimal set from roadmap (FR-007); sufficient for dashboard; users click through for details | Plan |
| Match score handling | Included (nullable float) | Users see scores immediately on list; null when job not yet evaluated; single LEFT OUTER JOIN avoids N+1 | Plan |
| Filtering | None | Frontend can filter client-side; keeps endpoint simple and aligned with MVP scope | Plan |
| Sorting | Fixed DESC by discovered_at | Newest jobs first matches Scout agent rescout behavior; no sort parameter needed | Plan |
| Invalid pagination | Clamp to valid range | Forgiving API; page 0 → page 1, page 999 → last page; frontend doesn't need validation | Plan |
| Authentication | Standard JWT only | Inherited from existing middleware; no additional rate limiting (Phase 2 feature) | Plan |

## Scope

**In scope:**
- GET /api/jobs endpoint with pagination
- LEFT OUTER JOIN with Evaluation table for optional match_score
- JobRepository.get_jobs_with_scores() method
- Pydantic response schemas (JobListItemResponse, GetJobsResponse)
- Unit tests for pagination, auth, multi-user isolation
- OpenAPI documentation
- Integration testing with real database

**Out of scope:**
- Filtering, searching, or advanced query parameters
- Sorting options beyond discovered_at DESC
- Rate limiting (Phase 2)
- Per-job caching or ETags
- Evaluation summaries (that's S-09)

## Architecture / Approach

**Data flow:**
1. User makes authenticated GET request with page/page_size
2. Endpoint extracts user_id from JWT token via auth dependency
3. JobRepository performs LEFT OUTER JOIN: Job + Evaluation (optional)
4. Results filtered by user_id, ordered by discovered_at DESC, paginated
5. Response includes pagination metadata + job list
6. Database indexes (ix_jobs_user_id, ix_jobs_url) ensure query efficiency

**API pattern matches existing endpoints:**
- Router registration in main.py
- Pydantic schemas for request/response validation
- FastAPI dependencies for auth + database session
- Async query execution via SQLAlchemy

## Phases at a Glance

| Phase | What it delivers | Key risk |
|-------|------------------|----------|
| 1. Repository & schemas | JobRepository.get_jobs_with_scores() method + Pydantic response models | LEFT OUTER JOIN correctness; ensuring null scores work as expected |
| 2. Endpoint implementation | GET /api/jobs route with pagination logic + router registration | Parameter validation (clamping); off-by-one in pagination offset |
| 3. Testing & isolation | Unit tests covering pagination, auth, multi-user scoping | Mock setup complexity; ensuring test isolation doesn't mask real bugs |
| 4. Integration & docs | Real database testing + OpenAPI documentation | Confirmation that pagination works end-to-end with real data |

**Prerequisites:**
- PostgreSQL running with jobs table (F-02)
- FastAPI server and auth middleware live (F-01, F-03)
- S-06 workflow has run to populate test jobs

**Estimated effort:**
~1–2 sessions. Phase 1 (repository + schemas) is lightweight. Phase 2 (endpoint) is straightforward copy of existing patterns. Phase 3 (tests) is the heavier lift. Phase 4 (integration) is validation, not new code.

## Open Risks & Assumptions

- **Assumption:** Jobs are populated by S-06 workflow before users call /jobs. If workflow hasn't run, user sees empty list (expected behavior, not a bug).
- **Risk:** LEFT OUTER JOIN performance with large job counts. Mitigation: indexes on (user_id, discovered_at) ensure efficient queries; pagination limits result set.
- **Risk:** Pagination offset becomes wrong if user_id filter excludes some jobs. Mitigation: count_by_user() filters same way as get_jobs_with_scores(); consistency enforced by tests.

## Success Criteria (Summary)

1. Endpoint returns paginated jobs for authenticated user
2. Pagination works correctly: page 1 vs page 2 return different jobs
3. Match scores appear when evaluations exist; null when not
4. Multi-user isolation enforced: user A can't see user B's jobs
5. API documentation appears in OpenAPI /docs
