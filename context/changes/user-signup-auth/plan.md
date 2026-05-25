# User Signup & Authentication — Implementation Plan

## Overview

Implement a user-facing signup and login interface that integrates with the FastAPI auth endpoints (F-03). Users can create an account with email + password, receive JWT tokens, and maintain sessions across page reloads. This is the north star slice — proves multi-user infrastructure works end-to-end.

## Current State Analysis

**Backend ready (F-01, F-02, F-03 completed):**
- FastAPI server running on port 8000 with async agents
- Auth endpoints live: POST `/api/signup`, `/api/login`, `/api/refresh`
- PostgreSQL + User schema with bcrypt password hashing
- JWT tokens: 24-hour access tokens, 30-day refresh tokens (configurable)
- Password requirements: 8+ chars, 1 digit, 1 uppercase letter

**Frontend gap:**
- No user-facing signup or login interface
- No token storage or session persistence
- No form validation or error feedback

### Key Discoveries

- Auth endpoints expect JSON requests with structured responses: `{ access_token, refresh_token, expires_in }`
- Password validation happens server-side; frontend provides visual hints
- Signup returns tokens immediately (auto-login); no separate confirmation email flow
- Token expiration is 24 hours (configurable via config); refresh endpoint can extend session to 30 days
- Refresh tokens should be stored in httpOnly cookies (XSS-safe) while access tokens can use localStorage for flexibility

## Desired End State

After this plan is complete:
- User visits `http://localhost:8000/` and sees signup form
- User enters email + password, form provides real-time validation feedback
- On successful signup, user sees success message and redirects to `/login`
- User can log in with email + password, tokens are stored and persist across page reloads
- User's access token is automatically refreshed before expiration (via refresh endpoint)
- Full auth flow is testable manually via browser with real data in PostgreSQL

### Verification Method

1. **Manual end-to-end**: signup → success message → login → redirect to dashboard (or confirmation page) → verify token in localStorage
2. **Token persistence**: Refresh page → tokens still present, ready for API calls
3. **Error cases**: Duplicate email → 409 error, weak password → validation message, wrong password on login → 401 error

## What We're NOT Doing

- Password reset / forgot password flow (future)
- Email verification or confirmation (implicit signup = confirmed)
- OAuth / social login (future)
- User profile/settings pages (future)
- CSRF protection (defer to full frontend in Phase 2)
- Server-side session management (stateless JWT only)
- Rate limiting on auth endpoints (future)

## Implementation Approach

Build a minimal, single-page form-based interface with vanilla JavaScript. The frontend is a static HTML file served from FastAPI with inline JavaScript handling form submission, validation, and token management. No build step, no external dependencies — just HTML, CSS, and vanilla JS.

Token lifecycle:
1. **Signup/Login**: POST to `/api/signup` or `/api/login` → receive `access_token` + `refresh_token`
2. **Store**: Access token → localStorage; refresh token → httpOnly cookie (set by server via Set-Cookie header)
3. **Use**: Add `Authorization: Bearer <access_token>` header to protected API calls
4. **Refresh**: When access token expires (401 response), POST to `/api/refresh` with refresh token → get new access token
5. **Logout**: Delete tokens from localStorage (client-side only; server-side revocation deferred)

## Critical Implementation Details

### Token Storage & CORS

The API must set refresh tokens via `Set-Cookie` with `httpOnly=True, Secure=True, SameSite=Lax`. FastAPI's response must include:
```python
response.set_cookie("refresh_token", token, httpOnly=True, max_age=30*24*60*60)
```

Frontend accesses the refresh token transparently when calling `/api/refresh` — the browser sends it automatically. Access token lives in localStorage for programmatic access.

### Real-Time Password Validation

Client-side validation shows rules as hints (green checkmark when met, red when not):
- Length: 8+ characters
- Digit: at least one number (0-9)
- Uppercase: at least one uppercase letter (A-Z)

Rules are checked as the user types; submit is disabled until all rules pass.

### Error Handling

API errors return structured JSON:
```json
{
  "error": "validation_error",
  "detail": "Password must contain at least one uppercase letter",
  "code": "INVALID_PASSWORD"
}
```

Frontend displays:
- **Inline errors**: Next to the offending field (e.g., "Email already registered" below email input)
- **Summary banner**: At top of form for API errors or unexpected failures

---

## Phase 1: Frontend Infrastructure & HTML Structure

### Overview

Create a static HTML page served from FastAPI root path (`/`). Set up basic form structure, CSS styling, vanilla JavaScript utilities for API calls and token management. No framework, no build step.

### Changes Required

#### 1. Create HTML Template

**File**: `ui/auth.html` (or `src/api/static/index.html`)

**Intent**: Single static HTML page with signup and login forms. Forms are initially hidden/shown via JavaScript toggle. Contains all HTML, CSS (inline `<style>`), and JavaScript (inline `<script>`).

**Contract**: 
- Root element is `<div id="auth-container">`
- Two form divs: `#signup-form` and `#login-form` (initially, signup is visible, login is hidden)
- Form inputs: email, password, password_confirm (signup only)
- Validation hints div: `#password-hints` (shows real-time feedback)
- Error banner: `#error-banner` (for API errors)
- Success message: `#success-message` (hidden until signup succeeds)
- Submit buttons: `#signup-btn`, `#login-btn`
- Toggle link: "Already have account? Log in" / "Need account? Sign up"
- Basic styling: centered layout, readable fonts, form inputs, button styles

#### 2. Create JavaScript Utilities

**File**: `ui/auth.html` (inline `<script>` section)

**Intent**: Core API client and token management functions.

**Contract**:

```javascript
// API call with Authorization header
async function apiCall(endpoint, method, body = null) {
  const headers = { "Content-Type": "application/json" };
  const token = localStorage.getItem("access_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;
  
  const options = { method, headers };
  if (body) options.body = JSON.stringify(body);
  
  const response = await fetch(`/api${endpoint}`, options);
  if (!response.ok) {
    const error = await response.json();
    throw { status: response.status, ...error };
  }
  return response.json();
}

// Token storage
function storeTokens(accessToken, refreshToken) {
  localStorage.setItem("access_token", accessToken);
  // refreshToken is managed by Set-Cookie (httpOnly); no need to store
}

function clearTokens() {
  localStorage.removeItem("access_token");
  // Refresh token cleared by server on logout
}

function getAccessToken() {
  return localStorage.getItem("access_token");
}
```

### Success Criteria

#### Automated

- HTML is valid and loads without JavaScript errors: `uv run python -c "from src.api.main import app; print(app.openapi())" > /dev/null`
- Form elements exist and are selectable: `document.querySelector("#signup-form")` is not null
- API utilities can be called in browser console without errors

#### Manual

- Open `http://localhost:8000/` in browser → signup form is visible
- Browser DevTools Console has no JavaScript errors on page load
- Form inputs are styled and readable
- Toggle link switches between signup and login forms

---

## Phase 2: Signup Form Submission & Validation

### Overview

Wire the signup form to POST `/api/signup`. Implement real-time password validation hints. Handle form submission, prevent submit while invalid, display server errors inline.

### Changes Required

#### 1. Real-Time Password Validation

**File**: `ui/auth.html` (JavaScript in signup form section)

**Intent**: As user types password, show visual feedback for each requirement.

**Contract**:

```javascript
function checkPasswordStrength(password) {
  return {
    length: password.length >= 8,
    digit: /\d/.test(password),
    uppercase: /[A-Z]/.test(password)
  };
}

function updatePasswordHints(password) {
  const hints = checkPasswordStrength(password);
  document.getElementById("hint-length").className = hints.length ? "valid" : "invalid";
  document.getElementById("hint-digit").className = hints.digit ? "valid" : "invalid";
  document.getElementById("hint-uppercase").className = hints.uppercase ? "valid" : "invalid";
  
  // Disable submit if not all requirements met
  document.getElementById("signup-btn").disabled = !Object.values(hints).every(Boolean);
}

// Attach to password input onchange
document.getElementById("password").addEventListener("input", (e) => {
  updatePasswordHints(e.target.value);
});
```

#### 2. Form Submission Handler

**File**: `ui/auth.html` (JavaScript signup section)

**Intent**: POST to `/api/signup`, handle success and errors.

**Contract**:

```javascript
async function handleSignup(email, password, passwordConfirm) {
  // Validate password_confirm matches
  if (password !== passwordConfirm) {
    showInlineError("password_confirm", "Passwords do not match");
    return;
  }
  
  try {
    const data = await apiCall("/signup", "POST", { email, password });
    storeTokens(data.access_token, data.refresh_token);
    showSuccessMessage("Account created! Redirecting to login...");
    setTimeout(() => toggleForm("login"), 2000);
  } catch (error) {
    if (error.status === 409) {
      showInlineError("email", "Email already registered");
    } else if (error.status === 400) {
      showInlineError("password", error.detail || "Invalid password");
    } else {
      showBannerError(error.detail || "Signup failed. Please try again.");
    }
  }
}

document.getElementById("signup-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const passwordConfirm = document.getElementById("password_confirm").value;
  handleSignup(email, password, passwordConfirm);
});
```

#### 3. Error Display

**File**: `ui/auth.html` (CSS + JavaScript)

**Intent**: Show inline field errors and banner errors.

**Contract**:

CSS classes:
```css
.error { color: #d32f2f; font-size: 0.8rem; }
.error-banner { background: #ffebee; border: 1px solid #d32f2f; padding: 10px; }
.hint.valid { color: #4caf50; } /* green */
.hint.invalid { color: #d32f2f; } /* red */
```

JavaScript:
```javascript
function showInlineError(fieldName, message) {
  const field = document.getElementById(fieldName);
  field.classList.add("error-input");
  const errorDiv = field.nextElementSibling || document.createElement("div");
  errorDiv.className = "error";
  errorDiv.textContent = message;
  if (!field.nextElementSibling) field.parentNode.insertBefore(errorDiv, field.nextSibling);
}

function clearInlineErrors() {
  document.querySelectorAll(".error").forEach(el => el.remove());
  document.querySelectorAll(".error-input").forEach(el => el.classList.remove("error-input"));
}

function showBannerError(message) {
  const banner = document.getElementById("error-banner");
  banner.textContent = message;
  banner.style.display = "block";
}

function clearBannerError() {
  document.getElementById("error-banner").style.display = "none";
}
```

### Success Criteria

#### Automated

- Form submit calls apiCall with correct endpoint: `npm test tests/auth-form.js` (or manual verification)
- Password validation logic correctly checks all requirements: `console.assert(checkPasswordStrength("Password1").all, "should validate strong password")`
- Type checking passes: `uv run mypy` (N/A for JS, but server-side auth is type-checked)

#### Manual

- Type weak password in signup form → hints show red X for failed requirements, submit button is disabled
- Type strong password → hints all turn green, submit becomes enabled
- Click signup with duplicate email → see "Email already registered" inline error below email field
- Passwords don't match → see error below password_confirm field
- Successful signup → see success message, page redirects to login form after 2 seconds

---

## Phase 3: Login Form Submission

### Overview

Implement login form with email + password fields. Wire to POST `/api/login` endpoint. Store tokens and prepare for next phase (protected API calls).

### Changes Required

#### 1. Login Form Submission Handler

**File**: `ui/auth.html` (JavaScript login section)

**Intent**: POST to `/api/login`, store tokens, display errors.

**Contract**:

```javascript
async function handleLogin(email, password) {
  try {
    clearBannerError();
    const data = await apiCall("/login", "POST", { email, password });
    storeTokens(data.access_token, data.refresh_token);
    showSuccessMessage("Logged in! Redirecting to dashboard...");
    // Redirect to dashboard or home (defer exact URL to Phase 4)
    setTimeout(() => window.location.href = "/dashboard", 2000);
  } catch (error) {
    if (error.status === 401) {
      showBannerError("Invalid email or password");
    } else {
      showBannerError(error.detail || "Login failed. Please try again.");
    }
  }
}

document.getElementById("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  handleLogin(email, password);
});
```

#### 2. Form Toggle

**File**: `ui/auth.html` (JavaScript)

**Intent**: Switch between signup and login forms without page reload.

**Contract**:

```javascript
function toggleForm(form) {
  clearBannerError();
  clearInlineErrors();
  document.getElementById("signup-form").style.display = form === "signup" ? "block" : "none";
  document.getElementById("login-form").style.display = form === "login" ? "block" : "none";
}

document.getElementById("toggle-login").addEventListener("click", () => toggleForm("login"));
document.getElementById("toggle-signup").addEventListener("click", () => toggleForm("signup"));
```

### Success Criteria

#### Automated

- Login endpoint responds with tokens: `curl -X POST http://localhost:8000/api/login -d '{"email":"test@test.com","password":"Pass1"}'` returns `{access_token, refresh_token}`
- Form submit calls correct endpoint and stores tokens in localStorage

#### Manual

- On login form, enter valid credentials → see "Logged in!" message
- Check browser DevTools: localStorage has `access_token` key with JWT value
- Invalid credentials → see "Invalid email or password" in banner
- Page redirects after 2 seconds (or stays if no /dashboard yet)

---

## Phase 4: Token Refresh & Protected Route Handler

### Overview

Implement automatic token refresh logic. When access token expires (401 response), automatically call `/api/refresh` to get a new token and retry the request. Add helper to inject Authorization header in all API calls.

### Changes Required

#### 1. Token Refresh Logic

**File**: `ui/auth.html` (JavaScript utilities)

**Intent**: Intercept 401 errors, refresh token, retry original request.

**Contract**:

```javascript
async function apiCall(endpoint, method, body = null) {
  let token = localStorage.getItem("access_token");
  
  // First attempt
  let response = await makeRequest(endpoint, method, body, token);
  
  // If 401 (token expired), refresh and retry once
  if (response.status === 401 && token) {
    const refreshed = await refreshToken();
    if (refreshed) {
      token = localStorage.getItem("access_token");
      response = await makeRequest(endpoint, method, body, token);
    }
  }
  
  if (!response.ok) {
    const error = await response.json();
    throw { status: response.status, ...error };
  }
  return response.json();
}

async function makeRequest(endpoint, method, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  
  const options = { method, headers };
  if (body) options.body = JSON.stringify(body);
  
  return fetch(`/api${endpoint}`, options);
}

async function refreshToken() {
  try {
    // Refresh token is in httpOnly cookie; browser sends it automatically
    const response = await fetch("/api/refresh", { 
      method: "POST",
      credentials: "include" // Include cookies
    });
    
    if (response.ok) {
      const data = await response.json();
      localStorage.setItem("access_token", data.access_token);
      return true;
    }
  } catch (error) {
    console.error("Token refresh failed:", error);
  }
  return false;
}
```

#### 2. Session Persistence on Page Reload

**File**: `ui/auth.html` (JavaScript initialization)

**Intent**: Check for existing token on page load; redirect to dashboard if logged in.

**Contract**:

```javascript
window.addEventListener("DOMContentLoaded", () => {
  const token = localStorage.getItem("access_token");
  
  // If user already logged in, redirect to dashboard
  if (token && !window.location.pathname.startsWith("/dashboard")) {
    // For now, just show a "you're logged in" message
    // Full redirect to dashboard happens in Phase 5
    console.log("User is authenticated; token persists");
  }
});
```

#### 3. Logout Handler

**File**: `ui/auth.html` (JavaScript)

**Intent**: Clear tokens and show logout confirmation.

**Contract**:

```javascript
function logout() {
  clearTokens();
  clearBannerError();
  clearInlineErrors();
  // Optional: POST to /api/logout for server-side revocation (deferred)
  showSuccessMessage("Logged out. Redirecting to signup...");
  setTimeout(() => toggleForm("signup"), 2000);
}
```

### Success Criteria

#### Automated

- Refresh endpoint is callable: `curl -X POST http://localhost:8000/api/refresh` returns new access_token
- Type checking on auth utilities passes (Python backend auth.utils already type-checked from F-03)

#### Manual

- Sign up, get tokens, check localStorage
- Manually delete access_token from localStorage via DevTools
- Try to call a protected API endpoint (if one exists) → should trigger refresh → get new token
- Refresh page → tokens still present, app remembers user is logged in
- Close browser tab/window → sessionStorage clears (localStorage persists); reopen app → tokens still there, user stays logged in

---

## Phase 5: Testing & Verification

### Overview

Manually test the complete auth flow end-to-end through the browser. Verify signup, login, token persistence, and error cases.

### Changes Required

#### 1. Ensure `/dashboard` Endpoint Exists (or minimal redirect target)

**File**: `src/api/main.py` (or `src/api/routes/auth.py`)

**Intent**: After login, users should redirect somewhere. For this phase, create a minimal "you're logged in" page.

**Contract**:

```python
@app.get("/dashboard")
async def dashboard(user: User = Depends(get_current_user)):
    return {
        "message": f"Welcome, {user.email}!",
        "user_id": user.id
    }
```

Or serve a simple HTML file:
```python
@app.get("/dashboard")
async def dashboard(user: User = Depends(get_current_user)):
    return FileResponse("ui/dashboard.html")
```

#### 2. Manual Test Checklist

**File**: N/A (manual testing in browser)

**Test cases**:
1. **Signup flow**: Navigate to `/` → enter email + strong password → click signup → see success message → redirected to login form
2. **Login flow**: On login form, enter credentials from step 1 → click login → see success message → redirected to /dashboard → dashboard shows user email
3. **Token persistence**: After login, open DevTools → check localStorage for access_token → refresh page → still authenticated, dashboard loads
4. **Error cases**: 
   - Duplicate email signup → see inline error "Email already registered"
   - Weak password → hints show red, submit disabled
   - Wrong password on login → see banner error "Invalid email or password"
   - No email/password → see validation errors
5. **Token expiration**: (Manual setup required)
   - Delete access_token from localStorage
   - Try to call protected endpoint → should auto-refresh → show new token in localStorage
6. **Logout**: (If logout button added) Click logout → tokens cleared → redirected to signup form

### Success Criteria

#### Automated

- Start FastAPI server: `uv run python -c "from src.api.main import app; import uvicorn; uvicorn.run(app, host='0.0.0.0', port=8000)"`
- Run existing auth endpoint tests (from F-03): `uv run pytest tests/test_auth_endpoints.py -v` all pass
- Type checking: `uv run mypy src/api/` passes

#### Manual

- Open browser to `http://localhost:8000/`
- Complete signup → see success message + redirect to login
- Complete login with credentials from signup → see success message + redirect to /dashboard
- Verify dashboard shows logged-in user info
- Refresh page → user still logged in (tokens persist)
- Clear access_token from DevTools → try protected call → auto-refresh works
- Test error cases: duplicate email, weak password, wrong password

---

## Testing Strategy

### Unit Tests

- Password validation logic: `checkPasswordStrength()` returns correct booleans for all requirements
- Token storage/retrieval: `storeTokens()` and `getAccessToken()` work as expected
- Error parsing: `showInlineError()` formats errors correctly

### Integration Tests

- Full signup → login → authenticated state flow
- Token refresh on 401 error
- Session persistence across page reload
- Error scenarios: 409 duplicate, 401 invalid credentials, 400 validation

### Manual Testing

- Browser-based end-to-end signup/login
- DevTools inspection of localStorage and network requests
- Form validation visual feedback
- Error message display and clarity

## References

- FastAPI Auth Endpoints (F-03): `context/archive/2026-05-25-jwt-auth-middleware/plan.md`
- FastAPI Scaffold (F-01): `context/archive/2026-05-25-fastapi-scaffold/plan.md`
- PostgreSQL + User Schema (F-02): `context/archive/2026-05-25-postgresql-pgvector-setup/plan.md`
- Roadmap S-01 Details: `context/foundation/roadmap.md` (line 142–154)

---

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands.

### Phase 1: Frontend Infrastructure

#### Automated
- [x] 1.1 HTML template loads without JavaScript errors
- [x] 1.2 Form elements are accessible and styled

#### Manual
- [x] 1.3 Root path (`/`) serves signup form

### Phase 2: Signup Form Submission

#### Automated
- [x] 2.1 Password validation logic checks all requirements correctly
- [x] 2.2 Form submit calls `/api/signup` with correct payload

#### Manual
- [x] 2.3 Real-time password hints display correctly as user types
- [x] 2.4 Invalid password shows validation message
- [x] 2.5 Duplicate email shows inline error
- [x] 2.6 Successful signup shows message and redirects to login

### Phase 3: Login Form Submission

#### Automated
- [x] 3.1 Form submit calls `/api/login` with correct payload

#### Manual
- [x] 3.2 Valid login shows success message
- [x] 3.3 Tokens stored in localStorage after login
- [x] 3.4 Invalid credentials show error message
- [x] 3.5 Redirects to /dashboard after successful login

### Phase 4: Token Refresh & Protected Routes

#### Automated
- [x] 4.1 Token refresh logic is callable and returns new access token
- [x] 4.2 Auth utils type check correctly (Python backend)

#### Manual
- [x] 4.3 Auto-refresh triggers on 401 response
- [x] 4.4 Session persists across page reload
- [x] 4.5 Logout clears tokens and redirects

### Phase 5: Testing & Verification

#### Automated
- [x] 5.1 Auth endpoint tests pass: `uv run pytest tests/test_auth_endpoints.py -v`
- [x] 5.2 Type checking passes: `uv run mypy src/api/`

#### Manual
- [x] 5.3 Full signup → login → authenticated flow works end-to-end
- [x] 5.4 Error cases handled correctly (duplicate email, weak password, invalid credentials)
- [x] 5.5 Token refresh works when access token expires
- [x] 5.6 Session persists across page reloads
