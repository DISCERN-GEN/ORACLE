# ORACLE — Engineering Specification Package

**Autonomous Prediction Market Intelligence & Execution Engine**

| Property | Value |
|---|---|
| Package version | 1.0 |
| Date | 01 November 2026 |
| Status | Proposed engineering baseline |
| Primary exchange | Polymarket |
| Classification | Engineering design documents |

---

## Contents

This package contains the complete engineering baseline for ORACLE:

| File | Description |
|---|---|
| `ORACLE_Engineering_Blueprint_v1.0.pdf` | Full system architecture & engineering blueprint (27 pages) |
| `ORACLE_DATABASE_SCHEMA.md` | Complete SQL schema, indexes, partitioning, migrations and retention policy |
| `ORACLE_API_SPECIFICATION.md` | REST endpoint definitions, data contracts, error codes and RBAC |
| `ORACLE_AGENT_SPECIFICATION.md` | Agent reasoning loop, state machine, tools, memory and autonomy boundaries |
| `ORACLE_QUANTITATIVE_MODELS.md` | Wallet scoring, statistical validation, Bayesian forecasting, arbitrage and portfolio Kelly |
| `ORACLE_DEPLOYMENT_RUNBOOK.md` | Infrastructure, Docker, secrets, monitoring, backups, recovery and go-live gates |
| `README.md` | This file |

---

## Document Relationships

```
ORACLE Engineering Blueprint (PDF)
        │
        ├── ORACLE_DATABASE_SCHEMA.md
        ├── ORACLE_API_SPECIFICATION.md
        ├── ORACLE_AGENT_SPECIFICATION.md
        ├── ORACLE_QUANTITATIVE_MODELS.md
        └── ORACLE_DEPLOYMENT_RUNBOOK.md
```

The PDF is the authoritative high-level architecture.  
The five Markdown documents expand the critical subsystems to an implementation-ready level of detail.

**Recommended reading order**

1. Engineering Blueprint (PDF) — system vision and constraints  
2. Database Schema — data model foundation  
3. API Specification — service interfaces  
4. Quantitative Models — edge measurement and capital allocation  
5. Agent Specification — autonomous behaviour and safety boundaries  
6. Deployment Runbook — operational readiness  

---

## Core Operating Principle

> ORACLE does not copy successful traders.  
> It discovers, validates and independently exploits measurable predictive advantages.

Wallet activity is treated as an information signal, not an unquestionable trading instruction.

---

## Non-Negotiable Engineering Invariants

1. The agent must never directly access private signing credentials.  
2. No LLM output can independently authorise a financial transaction.  
3. No trade can execute without fresh market data.  
4. No arbitrage can be classified as guaranteed without settlement verification.  
5. No wallet can be classified as statistically skilled based solely on headline profits.  
6. No probability estimate can be accepted without recording its model and inputs.  
7. No risk limit can be modified by the autonomous agent.  
8. No position can bypass portfolio-level exposure controls.  
9. No unresolved reconciliation discrepancy can silently permit additional exposure.  
10. Every financial action must have a complete decision trace.  
11. Every model must be evaluated prospectively.  
12. The system must be capable of refusing to trade.  

---

## Initial Execution Mode

Research → Replay → Paper trading → Shadow → Guarded live execution  

Live mode is **disabled by default** and may only be enabled after all go-live criteria in the Deployment Runbook are satisfied and an authorised operator explicitly enables it.

---

## Technology Baseline (summary)

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI |
| Frontend | Next.js / TypeScript |
| Database | PostgreSQL (+ TimescaleDB optional) |
| Cache / streams | Valkey / Redis |
| Analytics | Polars, NumPy, SciPy, PyMC, DuckDB |
| Deployment | Docker |
| Observability | Prometheus, Grafana, OpenTelemetry |

---

## Disclaimer

These documents define the **target architecture and implementation requirements**.  

They do **not** represent:

- a completed software deployment  
- verified trading performance  
- guaranteed arbitrage  
- legal authorisation to trade  

Technical access to any venue does not establish legal permission.  
A formal regulatory, tax and eligibility assessment is required before any live capital is deployed.

---

## Next Steps

1. Review and ratify the five subsystem specifications.  
2. Establish the repository structure described in the Blueprint.  
3. Implement Phase 0 (foundation) and Phase 1 (wallet intelligence).  
4. Maintain the invariants above as hard gates in every subsequent phase.

---

**ORACLE Engineering Team**  
01 November 2026
