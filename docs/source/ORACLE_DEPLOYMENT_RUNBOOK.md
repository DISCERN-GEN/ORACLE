# ORACLE Deployment Runbook

| Property | Value |
|---|---|
| Document | ORACLE_DEPLOYMENT_RUNBOOK |
| Version | 1.0 |
| Date | 01 November 2026 |
| Status | Engineering baseline |
| Parent document | ORACLE Engineering Blueprint v1.0 |
| Scope | Infrastructure, Docker, secrets, monitoring, backups, recovery |

---

## 1. Environment Topology

```
DEVELOPMENT
    │
    ▼
RESEARCH
    │
    ▼
STAGING
    │
    ▼
PRODUCTION RESEARCH
    │
    ▼
PAPER / SHADOW
    │
    ▼
GUARDED LIVE EXECUTION
```

Each environment has:

- Separate credentials and configuration
- Separate database instances (or strongly isolated schemas)
- Separate object-storage prefixes
- Independent kill-switch state

Live execution is disabled by default and requires explicit operator enablement after all go-live criteria are met.

---

## 2. Recommended Initial Infrastructure

| Component | Recommendation |
|---|---|
| Compute | Linux server(s) or small managed instance group |
| Containers | Docker + Docker Compose (Kubernetes only when scale justifies it) |
| Database | PostgreSQL 16+ (TimescaleDB optional) |
| Cache / streams | Valkey or Redis |
| Object storage | S3-compatible |
| Backend | FastAPI services |
| Frontend | Next.js dashboard |
| Monitoring | Prometheus + Grafana |
| Tracing | OpenTelemetry |
| CI/CD | GitHub Actions |
| Secrets | Dedicated secret store (never in git) |

---

## 3. Docker Layout

```
infra/docker/
├── docker-compose.yml              # local / research
├── docker-compose.staging.yml
├── docker-compose.paper.yml
├── docker-compose.live.yml         # guarded; extra controls
├── Dockerfile.api
├── Dockerfile.agent
├── Dockerfile.execution
└── ...
```

### 3.1 Core Services (Compose)

| Service | Purpose |
|---|---|
| `api` | FastAPI public/internal API |
| `agent` | Persistent autonomous agent |
| `wallet_intelligence` | Wallet discovery & scoring workers |
| `news_ingestion` | Source polling & normalisation |
| `forecasting` | Probability models |
| `opportunity_engine` | Mispricing / arbitrage scanner |
| `risk_engine` | Deterministic risk approval |
| `execution_gateway` | Isolated order submission |
| `reconciliation` | Venue vs internal state |
| `postgres` | Primary database |
| `valkey` | Cache & streams |
| `prometheus` / `grafana` | Observability |

Execution gateway must run with the least privileges necessary and must not share the same secret scope as the LLM/agent processes.

---

## 4. Configuration & Secrets

### 4.1 Configuration Hierarchy

1. Environment variables
2. Mounted config files (non-secret)
3. Secret store (credentials, API keys, private keys)

### 4.2 Secret Categories

| Secret | Scope | Notes |
|---|---|---|
| Database credentials | All services that need DB | Rotatable |
| Polymarket API keys | Connectors, execution | Environment-specific |
| Signing keys / wallets | **Execution gateway only** | Never injected into agent or LLM context |
| Object storage keys | Ingestion, archival | Least privilege |
| Monitoring credentials | Observability stack | — |
| Operator SSO / tokens | Dashboard & admin APIs | RBAC enforced |

### 4.3 Rules

- Private keys never appear in logs, LLM prompts, notebooks, or source repositories.
- Live signing material is loaded only by the execution gateway process.
- Secret rotation procedures must be documented and tested.
- Compromise of any secret triggers SEV-1 procedures.

---

## 5. Database Operations

### 5.1 Migrations

- All schema changes via versioned migrations under `data/migrations/`.
- Apply with a controlled migration job; never auto-migrate on application start in production.
- Expand → migrate data → contract for breaking changes.

### 5.2 Backups

| Type | Frequency | Retention |
|---|---|---|
| Full logical (pg_dump) | Daily | ≥ 30 days |
| Continuous WAL / PITR | Continuous | ≥ 7–14 days |
| Object-store versioning | Continuous | Per bucket policy |

Backup restoration must be tested regularly. Document the exact restore commands for each environment.

### 5.3 Connection Hygiene

- Pool sizes tuned per service.
- Statement timeouts on analytical queries.
- Read replicas for heavy research workloads if needed.

---

## 6. Monitoring & Alerting

### 6.1 Golden Signals (per service)

- Latency
- Traffic / request rate
- Errors
- Saturation (CPU, memory, DB connections, queue depth)

### 6.2 Domain Metrics

**Ingestion**  
API latency, failures, rate-limits, missing data, WebSocket disconnects.

**Wallet intelligence**  
Wallets discovered/analysed, reconstruction exceptions, score distribution.

**Probability**  
Brier, log-loss, calibration drift, model disagreement.

**Opportunity**  
Opportunities detected, net EV distribution, false-positive rate, rejected opportunities.

**Risk**  
Portfolio exposure, drawdown, blocked orders, Kelly utilisation.

**Execution**  
Order latency, fill rate, slippage, rejects, cancellation rate, reconciliation discrepancies.

### 6.3 Alert Severity

| Severity | Examples | Response |
|---|---|---|
| SEV-1 | Unauthorised order, credential compromise, runaway execution, material account discrepancy | Disable new risk immediately, preserve evidence, incident procedures |
| SEV-2 | Reconciliation failure, stale data with execution enabled, risk service down | Block new orders, reconcile |
| SEV-3 | Source outage, model drift, ingestion degradation | Degraded / read-only mode |

---

## 7. Deployment Procedures

### 7.1 Standard Service Deployment

1. CI builds and tags immutable images.
2. Images are promoted environment-by-environment.
3. Database migrations run as a separate, reviewed job.
4. Services are rolled out with health-check gates.
5. Smoke tests (API health, critical paths) must pass.
6. Observability dashboards confirmed green.

### 7.2 Execution Gateway Deployment (extra care)

1. Confirm kill-switch state and risk limits.
2. Confirm no open reconciliation discrepancies.
3. Deploy with zero or minimal concurrent order capacity first.
4. Verify paper/shadow behaviour before any live enablement.
5. Live flag remains off until explicit operator action.

### 7.3 Configuration Changes

- Risk limit changes require risk-operator role (dual control recommended in live).
- Model promotion follows quant governance (research → paper influence → live influence).

---

## 8. Kill-Switch & Emergency Procedures

### 8.1 Kill-Switch

- Global or scoped (`live_only`, market, category).
- Activatable via API (`POST /risk/kill-switch`) and via operational runbook.
- When active, the agent enters observation-only mode; execution gateway rejects new live intents.

### 8.2 SEV-1 Response (summary)

1. Activate kill-switch / disable new risk.
2. Preserve logs, audit trail, order state, memory snapshots.
3. Rotate compromised credentials if applicable.
4. Reconcile venue vs internal positions.
5. Notify designated operators.
6. Post-incident review before re-enabling.

### 8.3 Reconciliation After Outage

Never assume local order state is correct after an interruption.  
Always reconcile against venue records before allowing additional exposure.

---

## 9. Backup & Recovery Checklist

- [ ] Daily logical backups verified
- [ ] PITR window meets RPO
- [ ] Object-store versioning enabled
- [ ] Restore tested in staging within last 90 days
- [ ] Execution reconciliation procedure documented and tested
- [ ] Secret recovery / rotation procedure documented
- [ ] Runbooks for SEV-1/2/3 accessible offline if needed

---

## 10. Go-Live Gate (Live Execution)

Live mode may be enabled only when all of the following are true:

1. Data completeness measured and acceptable
2. Wallet ranking statistically validated
3. Probability calibration meets predefined standards
4. Back-tests passed independent review
5. Paper execution reliable over a sufficient period
6. Risk controls pass automated tests
7. Order reconciliation reliable
8. Security review complete
9. Legal / regulatory eligibility confirmed
10. Authorised operator explicitly enables live mode

---

## 11. Operational Contacts & Ownership

Maintain an up-to-date list (outside this document if preferred for privacy) of:

- On-call engineer
- Risk operator
- Quant administrator
- Security contact
- Legal / compliance contact (for live trading questions)

---

## 12. Change Log Discipline

Every production change (code, config, risk limits, model promotion) must leave an audit record.  
Prefer automated capture via the audit_events table and CI deployment logs.

---

**END OF ORACLE_DEPLOYMENT_RUNBOOK v1.0**
