# Validation Endpoint — End-to-End Verification

Use these steps to verify the full flow: Scout output → `POST /api/validate_jobs` → Orchestrator-ready response.

## Prerequisites

- App running: `docker-compose up` or `uv run uvicorn src.api.main:app --reload`
- A valid JWT access token (from `POST /api/auth/login`)
- Replace `<TOKEN>` with your JWT in every command below

---

## 1. Happy path — all jobs valid

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "id": "job-1",
        "title": "Python Developer",
        "company": "Tech Corp",
        "url": "https://www.python.org/jobs/",
        "description": "Python role"
      }
    ]
  }' | python3 -m json.tool
```

**Expected:** `valid_jobs` has 1 entry, `rejected_jobs` is empty, HTTP 200.

---

## 2. Dead URL — HTTP_ERROR

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "id": "job-dead",
        "title": "Dead Job",
        "company": "Gone Corp",
        "url": "https://httpstat.us/404"
      }
    ]
  }' | python3 -m json.tool
```

**Expected:** `rejected_jobs[0].reason_code == "HTTP_ERROR"`, HTTP 200.

---

## 3. Invalid URL — URL_INVALID

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "id": "job-bad-url",
        "title": "Bad URL Job",
        "company": "Corp",
        "url": "N/A"
      }
    ]
  }' | python3 -m json.tool
```

**Expected:** `rejected_jobs[0].reason_code == "URL_INVALID"`, fast response (no HTTP call made).

---

## 4. Mixed — partial valid, partial rejected

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "jobs": [
      {
        "id": "job-valid",
        "title": "Active Job",
        "company": "Active Corp",
        "url": "https://www.python.org/jobs/"
      },
      {
        "id": "job-dead",
        "title": "Dead Job",
        "company": "Gone Corp",
        "url": "https://httpstat.us/404"
      },
      {
        "id": "job-bad",
        "title": "Bad URL",
        "company": "Corp",
        "url": "not-a-url"
      }
    ]
  }' | python3 -m json.tool
```

**Expected:** `valid_jobs` has 1 entry (job-valid), `rejected_jobs` has 2 entries with different reason codes.

---

## 5. Verify logs (summary only)

After any request, check server logs. You should see exactly:

```
INFO  | POST /validate_jobs — N jobs received from <email>
INFO  | Validated N jobs for <email>: X passed, Y rejected
```

No per-job lines should appear at INFO level (only DEBUG if debug_mode=True).

---

## 6. Unauthenticated request — 401

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Content-Type: application/json" \
  -d '{"jobs": []}' | python3 -m json.tool
```

**Expected:** HTTP 401.

---

## 7. Invalid request body — 422

```bash
curl -s -X POST http://localhost:8000/api/validate_jobs \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"jobs": "not-a-list"}' | python3 -m json.tool
```

**Expected:** HTTP 422 Unprocessable Entity.

---

## 8. OpenAPI / Swagger

Open `http://localhost:8000/docs` and find `POST /api/validate_jobs`.

Verify:
- Request body shows a realistic example with job fields
- Response body shows `valid_jobs` and `rejected_jobs`
- `reason_code` enum values are documented (`URL_INVALID`, `HTTP_ERROR`, `JOB_EXPIRED`, `VALIDATION_TIMEOUT`)
- You can execute the endpoint directly from Swagger UI using the "Try it out" button

---

## Orchestrator integration checklist

When the Orchestrator slice is implemented, confirm:

- [ ] Orchestrator calls `POST /api/validate_jobs` with Scout's `found_jobs` output
- [ ] Orchestrator reads `valid_jobs` from response and passes them to scoring
- [ ] Orchestrator handles empty `valid_jobs` gracefully (no valid jobs found)
- [ ] Orchestrator logs or surfaces `rejected_jobs` reason codes for observability
