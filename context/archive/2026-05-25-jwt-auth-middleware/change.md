---
change_id: jwt-auth-middleware
status: archived
created: 2026-05-25
updated: 2026-05-25
archived_at: 2026-05-25T00:00:00Z
---

# F-03: JWT Auth Middleware

Foundation piece for user authentication in AgenticHire AI.

**Outcome**: JWT token generation, password hashing (bcrypt), auth middleware attached to FastAPI routes. All endpoints except `/signup` and `/login` require valid JWT.

**PRD refs**: FR-001 (signup), FR-002 (login), Access Control Changes section

**Depends on**: F-01 (FastAPI server) ✓

**Unlocks**: S-01 (user signup/auth), S-02 (login/refresh), all downstream slices

**Key decisions**:
- Token expiration: 24 hours
- Refresh tokens: Yes (short-lived access + long-lived refresh)
- Password: Min 8 chars, 1 digit + 1 uppercase
- Public endpoints: /signup, /login, /health
- Error handling: 401 for invalid/expired, 403 for missing token
- Middleware pattern: FastAPI Depends() on protected endpoints
- JWT claims: user_id + email + exp, HS256

**Risk**: Auth is security-critical. Mitigation: use battle-tested libraries (PyJWT, passlib), comprehensive testing, code review.
