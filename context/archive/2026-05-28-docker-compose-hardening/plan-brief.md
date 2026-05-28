# Docker Compose Hardening — Plan Brief

> Full plan: `context/changes/docker-compose-hardening/plan.md`  
> Research: `context/changes/docker-compose-hardening/research.md`

## What & Why

The Phase 1 Docker setup is MVP-safe (6/10 production-readiness) but has critical operational gaps: unbounded log growth, no CPU limits (agents can saturate host), slow failure on bad config, and unnecessary security exposure (pgAdmin on host, orphaned ChromaDB volume).

F-05 hardens the system to production-ready (9/10) by addressing these gaps across 5 phases, executable within 1-2 weeks post-Phase-1 release. The outcome is a reproducible, observable, and safe Docker Compose deployment for local development and production use.

## Starting Point

Phase 1 delivered a solid foundation:
- Multi-stage Dockerfile with 60% size optimization ✓
- Health checks on db and api services ✓
- Memory limits (4GB api, 2GB db) ✓
- Network isolation and named volumes ✓
- Entrypoint orchestration (db wait, migrations) ✓

**But missing critical operations**:
- Log rotation — disk fills on 24h+ containers
- CPU limits — agents (Vision LLM) can saturate all cores
- Secrets validation — bad config causes 5+ min health check timeout
- pgAdmin exposed — unnecessary security risk
- ChromaDB orphaned — confusion about authoritative DB

## Desired End State

**After F-05, the system is**:

1. **Operationally safe**: Disk protected (log rotation), agents bounded (CPU limits), fast failure on bad config (pre-startup validation)
2. **Securely hardened**: No unnecessary ports exposed, secrets validated at startup, dev/prod separation clear
3. **Observable**: JSON structured logs ready for Phase 2 aggregation, graceful shutdown tested
4. **Data-safe**: ChromaDB deprecation path documented, no orphaned volumes
5. **Production-verified**: Health checks pass on startup, shutdown tested in CI, startup order validated

Users can run `docker-compose up -d` (dev) or `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (production) with confidence.

## Key Decisions Made

| Decision | Choice | Why | Source |
|----------|--------|-----|--------|
| **Scope** | Tier 1 + Tier 2 (critical safety + operational polish) | Full hardening ensures production readiness without deferring essential safety features | Plan |
| **Compose strategy** | Single file with environment overrides (docker-compose.prod.yml) | Minimal maintenance; prod is overlay; single schema | Plan |
| **Logging** | Docker rotation NOW + JSON structure prep | Immediate disk-fill prevention; Phase 2-ready for aggregation | Plan |
| **Secrets validation** | Entrypoint script (pre-uvicorn) | Fast failure (<1s) vs. 5+ min health check timeout | Plan |
| **CPU limits** | API only (db is bursty) | Agents capped; PostgreSQL can handle spikes | Plan |
| **pgAdmin** | Remove entirely | Clean security posture; minimal local deployment principle | Plan |
| **ChromaDB** | Remove from compose + migration note | Clear data authority; easy cleanup path; prevents confusion | Plan |
| **Shutdown testing** | Manual + CI gate | Catches signal-handling regressions without heavy load testing | Plan |
| **Timeline** | 1-2 weeks after Phase 1 release | Time to validate Phase 1 before hardening; realistic for 10-day effort | Plan |

## Scope

**In scope:**
- Log rotation configuration (Docker json-file driver: max-size 100m, max-file 10)
- CPU limits for api service (cpus=2, cpus_reservation=1)
- Pre-startup environment variable validation (secrets, database URL)
- docker-compose.prod.yml with production overrides (no pgAdmin, no bind mounts, tighter limits)
- JSON logging structure prep for Phase 2 aggregation
- Graceful shutdown testing (manual + CI gate)
- ChromaDB volume removal + migration documentation
- Environment variable reference documentation

**Out of scope:**
- Secret rotation automation (Phase 2: HashiCorp Vault, AWS Secrets Manager)
- Log aggregation integration (Phase 2: Datadog, Splunk, Loki)
- Load testing for graceful shutdown under concurrency
- Kubernetes or multi-region failover
- Container image signing, SBOM, OCI attestation
- pgAdmin authentication hardening (removal instead)

## Architecture / Approach

**Incremental hardening across 5 phases, each testable and backward-compatible:**

1. **Compose configuration** — Resource limits, production overrides, volume cleanup, log driver setup
2. **Secrets validation** — Pre-startup checks in entrypoint (fail fast on bad config)
3. **Logging infrastructure** — Docker rotation + JSON structure prep
4. **Testing gates** — CI shutdown and startup order verification
5. **Documentation** — Migration path, env reference, deployment guide

**Key principle**: All changes are additive (new files) or enhancements (existing files); Phase 1 systems upgrade incrementally without breaking changes.

## Phases at a Glance

| Phase | Deliverable | Key Risk |
|-------|-------------|----------|
| 1 | Compose hardening: CPU limits, log driver, prod overrides, MIGRATION.md | docker-compose syntax errors; old workflows break |
| 2 | Secrets validation in entrypoint (pre-uvicorn) | Bashisms fail on some shells; error messages unclear |
| 3 | JSON logging config in loguru + docs/observability.md | JSON format breaks existing log parsing; Phase 2 integration unclear |
| 4 | Graceful shutdown test + CI startup order gate | Docker version compat (--wait needs 2.1+); CI/CD integration |
| 5 | MIGRATION.md, env variable reference, deployment guide | Documentation falls out of sync; troubleshooting incomplete |

**Prerequisites:**
- Phase 1 complete and stable (all 8 slices shipped, db + api healthy)
- Access to modify docker-compose.yml, Dockerfile, CI config, documentation
- Test environment available (local Docker Compose or CI sandbox)

**Estimated effort**: 7-10 days (one person), executably in parallel phases (1-2 independent, 3-4 sequential, 5 at end):
- Phase 1 (compose + docs): 3 days
- Phase 2 (entrypoint): 1 day
- Phase 3 (logging): 2 days
- Phase 4 (testing): 2 days
- Phase 5 (documentation): 1 day

## Open Risks & Assumptions

- **Docker Compose version**: Phase 4 assumes Docker Compose 2.1+ for `docker-compose up --wait`. Older versions require polling workaround.
- **Vision LLM CPU pressure**: API cpu=2 limit may cause timeouts under heavy inference. Monitor during testing; adjust to cpus=4 on high-end machines if needed.
- **Log rotation disk space**: 100MB × 10 files = 1GB total logs. Long-running containers (30+ days) may need external log aggregation. Phase 2 required for true observability.
- **Backward compatibility**: Phase 1 deployments must run migrations on upgrade (standard `docker-compose up -d` does this automatically).
- **ChromaDB migration**: Assumes pgvector migration succeeded in Phase 1. If CVs still only in ChromaDB, upgrade path requires manual data transfer (deferred to Phase 2 if needed).

## Success Criteria (Summary)

- ✓ docker-compose validates with new resource limits, log driver, prod overrides
- ✓ Missing secrets cause fast startup failure (<1s) with clear error
- ✓ `docker-compose kill -s SIGTERM` exits cleanly; no zombie processes
- ✓ `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up --wait` passes in CI
- ✓ MIGRATION.md enables safe upgrade from Phase 1 (tested on real system)
- ✓ System ships at 9/10 production-readiness; Phase 2 adds observability

---

**Ready to implement**: All decisions made, design validated, no open questions. Proceed to Phase 1 with `/10x-implement docker-compose-hardening phase 1`.
