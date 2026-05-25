# User Signup & Authentication — Plan Brief

> Full plan: `context/changes/user-signup-auth/plan.md`
> Roadmap: `context/foundation/roadmap.md` (S-01)

## What & Why

Build a user-facing signup and login interface for the FastAPI auth endpoints that were implemented in F-03. This is the north star slice — it proves the entire multi-user infrastructure (auth, database, JWT tokens) works end-to-end. Users can now create accounts, receive JWT tokens, and maintain persistent sessions. This unlocks all downstream slices (job search, evaluations, CV upload).

## Starting Point

FastAPI is running with complete auth endpoints (`/api/signup`, `/api/login`, `/api/refresh`). PostgreSQL has the User schema with bcrypt password hashing. JWT tokens are configured (24-hour access, 30-day refresh, HS256 signing). But there's no frontend — users can't yet interact with the system through a browser. We need a signup/login interface.

## Desired End State

User visits `http://localhost:8000/`, fills out signup form with email + strong password, receives JWT tokens, sees success message, redirects to login page. User logs in, tokens persist in localStorage (access) and httpOnly cookies (refresh), page redirects to /dashboard. User's session survives page reloads and auto-refreshes tokens before expiration.

## Key Decisions Made

| Decision                       | Choice            | Why (1 sentence)  | Source           |
| ------------------------------ | ----------------- | ----------------- | ---------------- |
| Frontend tech                  | Minimal HTML + vanilla JS | Zero build complexity, works immediately, aligns with MVP scope | Plan |
| Where to serve                 | Root path (/)     | Obvious entry point, simplest routing | Plan |
| Token storage                  | localStorage (access) + httpOnly cookies (refresh) | Balances security (XSS-proof refresh) and convenience (persistent access token) | Plan |
| Success redirect               | Login page        | Teaches full flow, separate signup/login forms clarify intent | Plan |
| Password validation            | Client + server   | Real-time feedback (fast) + server as source of truth (secure) | Plan |
| Error display                  | Inline + summary banner | Users know exactly which field is wrong + see API errors clearly | Plan |
| Login form scope               | Include in S-01   | North star isn't usable without login; keeps auth flow complete | Plan |
| Token refresh                  | Silent background refresh | Seamless UX; access token expires after 24h but refresh token extends to 30 days | Plan |

## Scope

**In scope:**
- Single-page HTML form (signup + login)
- Real-time password validation hints
- Form submission to F-03 auth endpoints
- Token storage (localStorage + cookies)
- Error handling and inline field errors
- Session persistence across page reloads
- Automatic token refresh on 401

**Out of scope:**
- Password reset / forgot password
- Email verification or confirmation
- OAuth / social login
- Full dashboard/home page (minimal redirect only)
- CSRF protection (defer to Phase 2 React frontend)
- Rate limiting on auth endpoints

## Architecture / Approach

Single static HTML file served from FastAPI root. Forms collect email + password, validate client-side for UX, submit to `/api/signup` or `/api/login`. Backend returns `{ access_token, refresh_token, expires_in }`. Frontend stores access token in localStorage and refresh token in httpOnly cookie (set by server). All subsequent API calls include `Authorization: Bearer <token>` header. When token expires (401 response), automatically POST to `/api/refresh` to get new token.

```
User → HTML Form (/) → POST /api/signup → Backend creates User + issues tokens
                    ↓
                  Store tokens (localStorage + cookie)
                    ↓
                  Redirect to /login
                    ↓
User → Login Form → POST /api/login → Backend verifies password + issues tokens
                    ↓
                  Store tokens
                    ↓
                  Redirect to /dashboard (minimal page)
                    ↓
User is authenticated; tokens refresh silently on 401
```

## Phases at a Glance

| Phase     | What it delivers       | Key risk                  |
| --------- | ---------------------- | ------------------------- |
| 1. Frontend Infrastructure | HTML form structure, CSS styling, JS utilities for API calls and token management | HTML loads without errors; JS utilities callable |
| 2. Signup Form | Form submission to `/api/signup`, real-time password validation, error display | Validation logic matches backend requirements; API integration works |
| 3. Login Form | Form submission to `/api/login`, token storage, form toggle | Login endpoint integration; tokens properly stored |
| 4. Token Refresh | Auto-refresh on 401, session persistence across reloads, logout | Refresh token lifecycle; httpOnly cookie handling |
| 5. Testing & Verification | End-to-end manual testing, error case validation, dashboard integration | All flows work in real browser; error messages are clear |

**Prerequisites:** F-01 (FastAPI running), F-02 (PostgreSQL + User schema), F-03 (auth endpoints live)
**Estimated effort:** ~3-4 sessions across 5 phases. Phase 1-2 are quickest (form structure + submission); Phase 4 (token refresh) requires careful async handling. Phase 5 is manual testing.

## Open Risks & Assumptions

- **httpOnly cookie handling**: Assumes FastAPI properly sets `Set-Cookie` header with `httpOnly=True, Secure=True`. If Secure flag is set, must test over HTTPS or disable for local dev.
- **CORS**: If frontend and API are on different ports, CORS headers must allow credentials (`credentials: include`). Current single-port setup avoids this.
- **Refresh token rotation**: Current plan doesn't rotate refresh tokens. If security posture changes, may need versioning / revocation list.
- **Dashboard endpoint**: Plan assumes `/dashboard` endpoint exists. If not, need minimal placeholder.

## Success Criteria (Summary)

- User can sign up via form, see success message, redirect to login
- User can log in, tokens are stored and persist across page reloads
- Session stays active for 24 hours (access token) with automatic refresh up to 30 days (refresh token)
- All error cases (duplicate email, weak password, invalid credentials) display clear, inline error messages
