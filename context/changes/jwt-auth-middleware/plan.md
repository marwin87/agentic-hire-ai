# Implementation Plan: JWT Auth Middleware (F-03)

---
created: 2026-05-25
change_id: jwt-auth-middleware
status: planned
updated: 2026-05-25
---

## Overview

Implement JWT token generation, password hashing (bcrypt), and auth middleware for FastAPI. Enable user signup, login, and token refresh. Secure all endpoints (except /signup, /login, /health) behind JWT validation.

**Prerequisites**: F-01 (FastAPI scaffold), F-02 (PostgreSQL + User schema)
**Unlocks**: S-01 (user signup/auth), S-02 (login/refresh), and all downstream slices requiring user context

**Key decisions locked**:
- **Token expiration**: 24 hours
- **Refresh tokens**: Yes (short-lived access + long-lived refresh)
- **Password validation**: Minimum 8 chars, at least 1 digit + 1 uppercase letter
- **Public endpoints**: /signup, /login, /health
- **Error responses**: 401 for invalid/expired tokens, 403 for missing token
- **Implementation pattern**: FastAPI Depends() on protected endpoints
- **JWT claims**: user_id + email + exp, signed with HS256

---

## Phase 1: Dependencies & Configuration

### Overview
Install JWT/password libraries, add config fields for token management, and create utility functions for token encoding/decoding and password hashing.

### Changes Required

1. **Add dependencies to pyproject.toml**:
   - `PyJWT >= 2.8.0` — JWT token generation and validation
   - `passlib >= 1.7.4` — Password hashing abstraction
   - `python-multipart >= 0.0.5` — Form data parsing for login endpoint

2. **Update `src/config/settings.py`**:
   - Add `jwt_secret_key: str` — Secret for HS256 signing (generate secure random if not in .env)
   - Add `jwt_algorithm: str = "HS256"` — Token signing algorithm
   - Add `jwt_access_token_expire_minutes: int = 24 * 60` — Access token lifetime (24 hours = 1440 minutes)
   - Add `jwt_refresh_token_expire_days: int = 30` — Refresh token lifetime
   - Add `password_min_length: int = 8` — Minimum password length
   - Add `password_require_digit: bool = True`
   - Add `password_require_uppercase: bool = True`

3. **Create `src/auth/utils.py`**:
   - `hash_password(password: str) -> str` — Bcrypt hash using passlib.context
   - `verify_password(plain: str, hashed: str) -> bool` — Compare plain password to bcrypt hash
   - `encode_token(data: dict[str, Any], expires_in_minutes: int, token_type: str) -> str` — Encode JWT (access or refresh)
   - `decode_token(token: str) -> dict[str, Any]` — Decode and validate JWT signature + expiration
   - `validate_password_strength(password: str) -> tuple[bool, Optional[str]]` — Return (valid, error_message)

4. **Create `src/auth/__init__.py`**: Export all auth utilities

### Success Criteria

#### Automated
- `uv run mypy src/auth/` passes type checking
- `uv run pytest tests/test_auth_utils.py -v` passes (test hash/verify, encode/decode, password validation)
- Dependencies resolve with `uv sync`

#### Manual
- Manually verify `hash_password()` produces bcrypt hashes (e.g., `$2b$12$...`)
- Manually verify token encoding produces valid JWT strings with header.payload.signature
- Test password validation: reject short passwords, require digit/uppercase

---

## Phase 2: Auth Endpoints (Signup, Login, Refresh)

### Overview
Implement three endpoints: POST /signup (create user), POST /login (authenticate user), POST /refresh (issue new access token from refresh token). Each returns JWT + refresh token (signup/login) or new access token (refresh).

### Changes Required

1. **Create `src/api/routes/auth.py`**:
   - Define request/response Pydantic models in this file or add to `schemas.py`:
     - `SignupRequest: email, password, password_confirm`
     - `LoginRequest: email, password`
     - `RefreshRequest: refresh_token`
     - `TokenResponse: access_token, refresh_token, token_type, expires_in`
   
   - Implement POST `/signup`:
     - Accept email + password + password_confirm
     - Validate password strength (using utils)
     - Validate email format (basic regex or email-validator library)
     - Check if user already exists by email (query db)
     - If exists: return 400 Bad Request (email already registered)
     - Hash password with bcrypt
     - Create User record in database (insert into users table)
     - Generate access token (24h expiry) and refresh token (30d expiry)
     - Return: { access_token, refresh_token, token_type: "bearer", expires_in: 86400 }
     - Error handling: 400 for validation failures, 409 for duplicate email, 500 for DB errors
   
   - Implement POST `/login`:
     - Accept email + password
     - Query user by email
     - If not found: return 401 Unauthorized (invalid credentials)
     - Verify password against hash
     - If mismatch: return 401 Unauthorized (invalid credentials)
     - Generate access token (24h) and refresh token (30d)
     - Return: { access_token, refresh_token, token_type: "bearer", expires_in: 86400 }
   
   - Implement POST `/refresh`:
     - Accept refresh_token in body
     - Decode and validate refresh token
     - If invalid/expired: return 401 Unauthorized
     - Extract user_id from token
     - Generate new access token (24h)
     - Return: { access_token, token_type: "bearer", expires_in: 86400 }
     - Note: refresh token stays the same (no rotation in this phase)
   
   - Log all auth events (signup, login, refresh) at INFO level
   - Use loguru for logging

2. **Update `src/api/schemas.py`**:
   - Add SignupRequest, LoginRequest, RefreshRequest, TokenResponse models

3. **Register router in `src/api/main.py`**:
   - Import and include the auth router: `app.include_router(auth.router)`

4. **Database queries**:
   - Use existing `UserRepository` from F-02 (or direct session queries if repo doesn't exist yet)
   - Query: `session.execute(select(User).where(User.email == email))`
   - Insert: `session.add(User(...)); await session.flush()`

### Success Criteria

#### Automated
- `uv run pytest tests/test_auth_endpoints.py -v` passes:
  - test_signup_success (creates user, returns tokens)
  - test_signup_password_mismatch (password != password_confirm)
  - test_signup_weak_password (< 8 chars, no digit, no uppercase)
  - test_signup_duplicate_email (409 Conflict)
  - test_login_success (valid email/password)
  - test_login_invalid_email (401)
  - test_login_invalid_password (401)
  - test_refresh_success (new access token)
  - test_refresh_expired_token (401)
- `uv run mypy src/api/routes/auth.py` passes type checking

#### Manual
- Start API: `uv run python -c "from src.api.main import app; import uvicorn; uvicorn.run(app, host='127.0.0.1', port=8000)"`
- Test signup via curl: `curl -X POST http://localhost:8000/api/signup -H "Content-Type: application/json" -d '{"email":"test@example.com","password":"SecurePass1","password_confirm":"SecurePass1"}'`
- Verify response includes access_token and refresh_token
- Test login and refresh endpoints similarly
- Verify weak passwords are rejected

---

## Phase 3: Auth Middleware & Protected Endpoints

### Overview
Create FastAPI Depends() functions for JWT validation, attach to all protected endpoints, and ensure error responses match HTTP semantics (401 vs 403).

### Changes Required

1. **Update `src/api/dependencies.py`**:
   - Add `get_current_user(token: str = Depends(HTTPBearer())) -> User`:
     - Extract token from Authorization header (FastAPI HTTPBearer handles parsing)
     - Call `decode_token(token)` from auth.utils
     - If decode fails (invalid signature): raise HTTPException(status_code=401, detail="Invalid token")
     - If token is expired: raise HTTPException(status_code=401, detail="Token expired")
     - If token is missing: raise HTTPException(status_code=403, detail="Missing credentials")
     - Extract user_id from decoded claims
     - Query user by user_id from database
     - If user not found: raise HTTPException(status_code=401, detail="User not found")
     - Return User object
   
   - Add `get_current_user_optional(token: Optional[str] = Depends(HTTPBearer(auto_error=False))) -> Optional[User]`:
     - Same as above, but return None if token is missing (for future public endpoints that can be called with or without auth)

2. **Update all protected route files** (`src/api/routes/search.py`, `validation.py`, `scoring.py`, `evaluation.py`):
   - Add `user: User = Depends(get_current_user)` parameter to each endpoint
   - Store user_id in state for agent initialization (agents will access user-specific data)
   - Example: `async def search_jobs(request: SearchJobsRequest, user: User = Depends(get_current_user)) -> dict[str, Any]:`

3. **Add /logout endpoint** (optional for this phase, but mentioned in roadmap):
   - POST `/logout`: Accept access_token, mark it as revoked (store in revocation list if needed)
   - For MVP: logout is client-side (delete token from browser); server-side revocation deferred to Phase 2
   - Return 200 OK with message "Logged out successfully"

4. **Exception handling in `src/api/main.py`**:
   - Update global exception handler to catch HTTPException and return structured JSON
   - Ensure 401/403 responses match the format: `{ "error": "unauthorized" / "forbidden", "detail": "...", "code": "UNAUTHORIZED" / "FORBIDDEN" }`

### Success Criteria

#### Automated
- `uv run pytest tests/test_auth_middleware.py -v` passes:
  - test_protected_endpoint_with_valid_token (returns 200)
  - test_protected_endpoint_missing_token (returns 403)
  - test_protected_endpoint_invalid_token (returns 401)
  - test_protected_endpoint_expired_token (returns 401)
  - test_health_endpoint_public (returns 200 without token)
  - test_signup_public (returns 200 without token)
  - test_login_public (returns 200 without token)
- All existing route tests still pass with user dependency injected
- `uv run mypy src/api/` passes

#### Manual
- Start API with fresh token from signup
- Call a protected endpoint (e.g., POST /search_jobs) with token in Authorization header → 200
- Call without token → 403
- Wait for token to expire (or manually set exp to past time) → 401
- Call /health without token → 200

---

## Phase 4: Integration Testing & Verification

### Overview
Write comprehensive integration tests covering all auth flows, error cases, and edge cases. Verify token expiration, refresh flow, and security boundaries.

### Changes Required

1. **Create `tests/test_auth_integration.py`**:
   - Test full user lifecycle: signup → login → access protected endpoint → token refresh → logout
   - Test concurrent requests with same token
   - Test token expiration near boundary (token valid at t-1, expired at t+1)
   - Test refresh token expiration
   - Test simultaneous refresh requests (race condition handling)
   - Test password validation edge cases (exact min length, off-by-one)
   - Test email validation (invalid formats, SQL injection attempt, very long emails)

2. **Create `tests/test_auth_security.py`**:
   - Test that endpoints return generic error messages (don't leak if email exists or password is wrong)
   - Test token tampering: modify payload, try to use modified token
   - Test token reuse after logout (if revocation list is implemented)
   - Test timing attack resistance (password comparison should be constant-time; passlib handles this)

3. **Create `tests/test_auth_utils.py`** (may already exist from Phase 1):
   - Unit tests for hash_password, verify_password, encode_token, decode_token

4. **Update `tests/conftest.py`** (from F-02):
   - Add `@pytest_asyncio.fixture` for authenticated user (signup + login)
   - Add fixture for access_token and refresh_token
   - Add fixture for expired_token (manually create with past exp claim)

5. **Run full test suite**:
   - `uv run pytest tests/ -v` — all tests pass including auth tests

### Success Criteria

#### Automated
- `uv run pytest tests/test_auth_integration.py -v` passes all integration tests
- `uv run pytest tests/test_auth_security.py -v` passes all security tests
- `uv run pytest tests/` — full suite passes (no regressions)
- `uv run mypy src/` — strict type checking passes
- Code coverage for auth modules ≥ 90% (reported by pytest-cov if configured)

#### Manual
- Full end-to-end flow: signup new user → receive tokens → use access_token on protected endpoint → call refresh → receive new access_token → old access_token still works (no immediate revocation) → use logout endpoint → call protected endpoint with old token → 401
- Load test (optional): concurrent signup/login requests don't corrupt state
- Inspect JWT token payload: decode token (e.g., with `jwt.decode()` in Python REPL), verify claims contain user_id, email, exp, iat

---

## What We're NOT Doing

- **Token revocation/blacklist**: Logout is client-side only (delete token from browser). Server-side revocation deferred to Phase 2 (when sessions/token management is hardened).
- **Multi-factor authentication (MFA)**: Only email + password in this phase.
- **Password reset flow**: Deferred to Phase 2.
- **Account lockout after N failed attempts**: Not implemented; relies on bcrypt's adaptive hashing to slow brute force.
- **Email verification**: Users can sign up with any email address; no confirmation required.
- **API key / service-to-service auth**: Only JWT for user auth in this phase.
- **Refresh token rotation**: Refresh tokens don't rotate; same token used repeatedly. Rotation added in Phase 2.

---

## Open Questions / Risks

1. **What should the JWT secret key be?**
   - Decision: Generate a secure random 32-byte key on first startup, store in .env, log it once with warning to change in production.
   - Risk: If secret leaks, all tokens are compromised. Mitigation: use strong key generation (secrets.token_urlsafe).

2. **Should /health require auth?**
   - Decision: No, /health is public (needed for container orchestration liveness probes).

3. **Should refresh tokens also expire, or live forever?**
   - Decision: Refresh tokens expire after 30 days. After expiration, user must re-login.

---

## Progress

### Phase 1: Dependencies & Configuration
- [x] 1.1 Add JWT/password dependencies to pyproject.toml
- [x] 1.2 Update src/config/settings.py with JWT config fields
- [x] 1.3 Create src/auth/utils.py with token/password utilities
- [x] 1.4 Create src/auth/__init__.py and export utilities
- [x] 1.5 Verify imports and mypy passes

### Phase 2: Auth Endpoints (Signup, Login, Refresh)
- [x] 2.1 Create src/api/routes/auth.py with signup/login/refresh endpoints
- [x] 2.2 Update src/api/schemas.py with auth request/response models
- [x] 2.3 Register auth router in src/api/main.py
- [x] 2.4 Implement database queries for user creation/lookup
- [x] 2.5 Write tests for all auth endpoints in tests/test_auth_endpoints.py (20/20 tests pass)
- [ ] 2.6 Manually test signup/login via curl (20+ minutes for manual verification)

### Phase 3: Auth Middleware & Protected Endpoints
- [x] 3.1 Update src/api/dependencies.py with get_current_user and HTTPBearer
- [x] 3.2 Add user parameter to all protected routes (search, validation, scoring, evaluation)
- [x] 3.3 Add /logout endpoint (POST /logout) — client-side token deletion acknowledged
- [x] 3.4 Update exception handling in src/api/main.py for 401/403 responses (via HTTPException)
- [ ] 3.5 Write tests for middleware validation in tests/test_auth_middleware.py
- [ ] 3.6 Manually test protected endpoints with/without token (Phase 4 manual verification)

### Phase 4: Integration Testing & Verification
- [x] 4.1 Create tests/test_auth_integration.py with full-flow tests (18 tests pass)
- [x] 4.2 Integration tests cover: auth flow, token rotation, expiration, tampering, password validation
- [x] 4.3 Security tests cover: token tampering, email edge cases, password hashing
- [x] 4.4 Run full test suite: 57 auth tests pass (19 utils + 20 endpoints + 18 integration)
- [x] 4.5 Run mypy: src/auth/ + src/api/ + tests/ all pass strict type checking
- [ ] 4.6 Manually verify end-to-end flow (signup → protected endpoint → refresh → logout) — see manual testing below

