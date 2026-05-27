---
change_id: user-job-list
title: User job list
status: archived
created: 2026-05-27
updated: 2026-05-27
archived_at: 2026-05-27T14:00:00Z
---

## Notes

**Frontend Integration (Phase 2):** The GET /api/jobs endpoint is complete and production-ready, but not yet integrated into the dashboard UI. Next phase should add a "Discovered Jobs" or "Job History" section to `ui/dashboard.html` that calls this endpoint with pagination. This will display the user's full job history with optional match scores from evaluations.
