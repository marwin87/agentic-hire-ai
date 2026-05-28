# Testing Guide

## Unit & Integration Tests

```bash
uv run pytest                          # all tests
uv run pytest tests/test_graph.py -v   # single file
uv run pytest -k test_name -v          # single test by name
```

Tests use `unittest.mock` for all external calls — no real API or DB access in unit tests.

## Docker Integration Tests

Run against a live Docker Compose stack:

```bash
DOCKER_INTEGRATION=true uv run pytest tests/integration/ -v
```

Requires a valid `.env` file with all required secrets (see `.env.example`).

---

## Manual Graceful Shutdown Verification

Use this procedure to verify SIGTERM handling after changes to the entrypoint script, uvicorn configuration, or Docker Compose resource limits.

### Steps

**1. Start services**
```bash
docker-compose up -d --build
```

**2. Verify healthy**
```bash
docker-compose ps
# Both services should show "(healthy)"
```

**3. Stop gracefully**
```bash
docker-compose stop
```

> Use `docker compose stop` — not `docker compose kill -s SIGTERM`.
> Both send SIGTERM, but `kill` triggers the `restart: unless-stopped` policy
> and containers come back up immediately. `stop` bypasses the restart policy.

**4. Verify clean exit**
```bash
docker-compose ps -a
# Should show "Exited (0)" for both services — NOT "Exited (1)" or still "Up"
```

**5. Check API logs for clean shutdown**
```bash
docker logs agentic-hire-api 2>&1 | tail -20
# Should NOT contain: "Traceback", "Error", "Killed", "OOM"
# uvicorn logs "Shutting down" on clean SIGTERM
```

**6. Verify no zombie processes**
```bash
ps aux | grep uvicorn | grep -v grep
# Should return nothing (all uvicorn processes exited)
```

### Expected outcome

```
NAME                STATUS
agentic-hire-api    Exited (0)
agentic-hire-db     Exited (0)
```

Exit code 0 = clean shutdown. Exit code 137 = SIGKILL (Docker killed it because it didn't exit within `stop_grace_period`, which defaults to 10s). If you see 137, investigate why uvicorn is not responding to SIGTERM.

### Increasing the grace period

If in-flight requests need more time to drain (e.g., long-running job scoring), increase the stop grace period in `docker-compose.yml`:

```yaml
services:
  api:
    stop_grace_period: 30s   # default is 10s
```
