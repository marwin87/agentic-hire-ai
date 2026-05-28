# Observability & Logging

## Current Setup

### Log Rotation (Docker driver)

All containers use the Docker `json-file` log driver with automatic rotation:

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "100m"   # rotate when file hits 100 MB
    max-file: "10"     # keep at most 10 rotated files (1 GB total per service)
```

Rotation is transparent — Docker handles it automatically on every container restart or when the size limit is reached.

**View logs:**
```bash
docker-compose logs -f api          # stream all api logs
docker logs --tail=100 agentic-hire-api   # last 100 lines
docker logs --since=1h agentic-hire-api  # last hour
```

**Inspect driver config:**
```bash
docker inspect agentic-hire-api | grep -A8 '"LogConfig"'
```

### Structured JSON Logging (opt-in)

The application uses [loguru](https://loguru.readthedocs.io/) for logging. By default it emits human-readable plain text to `stdout`.

Enable machine-parseable JSON by setting:

```bash
AGENTIC_HIRE_JSON_LOGS=true
```

JSON lines are written to `stderr` so they can be split from plain text output by log aggregation agents. Each line is a self-contained JSON object with fields: `text`, `record.time`, `record.level`, `record.message`, `record.name`, `record.function`, `record.line`.

**Parse JSON logs locally:**
```bash
docker logs agentic-hire-api 2>&1 | grep '^{' | jq '.record.level.name'
```

---

## Phase 2: Log Aggregation (placeholder)

When ready to ship to a managed log platform, configure the aggregation driver in `docker-compose.prod.yml` and set `AGENTIC_HIRE_JSON_LOGS=true`. The JSON structure is already stable.

### Datadog

```yaml
# docker-compose.prod.yml — add under api service
logging:
  driver: datadog
  options:
    dd-api-key: "${DD_API_KEY}"
    dd-source: python
    dd-service: agentic-hire-api
    dd-tags: "env:production"
```

### Loki (Grafana)

```yaml
logging:
  driver: loki
  options:
    loki-url: "http://loki:3100/loki/api/v1/push"
    loki-labels: "job=agentic-hire-api"
```

### Splunk

```yaml
logging:
  driver: splunk
  options:
    splunk-token: "${SPLUNK_HEC_TOKEN}"
    splunk-url: "https://splunk.example.com:8088"
    splunk-source: agentic-hire-api
```

> Replace the `logging:` block added by F-05 (`json-file`) with the aggregation driver block above in `docker-compose.prod.yml`. The base `docker-compose.yml` keeps `json-file` for local development.

---

## Key Metrics to Watch (Phase 2)

| Metric | What it means | Alert threshold |
|--------|---------------|-----------------|
| Container restarts | Crash loop or OOM | > 3 in 10 min |
| Memory usage | Agent memory leak | > 3.5 GB (near 4 GB limit) |
| CPU usage | Runaway agent | > 190% of 2-core limit |
| Log volume | Verbose debug mode in prod | > 50 MB/min |
| Health check failures | API not responding | Any failure |
