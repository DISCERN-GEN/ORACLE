# ORACLE — Consolidated Private Implementation Plan v1.1

**Date:** 01 November 2026  
**Owner model:** Private, single owner / personal use  
**Primary venue:** Polymarket (read-only integration first)  
**Execution progression:** Research → Replay → Paper → Shadow → Guarded live, subject to legal and operational approval

## 1. Objective

Build the complete ORACLE system as a private, owner-operated platform. All major subsystems are to be implemented and integrated before the first full operational deployment. This is not a commercial release, SaaS product or multi-tenant service. The system is designed for one owner initially, with a modular architecture that does not prevent future extension.

## 2. Agreed operating sequence

1. Implement and integrate all core services, database entities, API contracts, dashboard, observability, persistence, recovery and security controls.
2. Deploy with live public market data and a simulated bankroll. No wallet signing, deposits or real orders are used.
3. Run an unattended 12-hour acceptance session. The agent observes live markets, refreshes selected order books, records wallet and event data, calculates forecasts only where an approved model exists, evaluates candidate opportunities, and routes any permitted simulated orders through the risk engine and paper broker.
4. Produce a machine-generated test report. A 12-hour pass confirms operational continuity only; it does not prove predictive edge or profitability.
5. Continue prospective paper and shadow validation over a statistically meaningful period. No automatic conversion from paper to live is allowed.
6. Consider guarded live operation only after separate legal, venue eligibility, security, model validation, reconciliation and explicit owner approval gates.

## 3. Complete system scope

| Subsystem | Required deliverables | Acceptance evidence |
|---|---|---|
| Data ingestion | Gamma, CLOB, Data API, market WebSocket, REST reconciliation, raw payload archive, retry/rate-limit handling | Measured data freshness/completeness, recoverable ingestion cursors |
| Wallet intelligence | Up to 10,000 candidate wallets, trade/position reconstruction, P&L, CLV, concentration, classifications, FDR and OOS validation | Reproducible profiles, sample-size warnings, OOS evidence |
| News/event intelligence | Source registry, polling/connectors, document hashes, claim extraction, contradiction tracking, event graph, market-resolution mapping | Every claim has provenance; conflicting claims remain visible |
| Probability intelligence | Base rates, Bayesian updates, specialist model interface, calibrated ensemble, model cards, Brier/log-loss | Versioned forecasts with intervals, evidence and invalidation conditions |
| Opportunity engine | Executable price/depth, fees, slippage, directional EV, complete-set and related-market checks | Reproducible net EV and arbitrage verification records |
| Portfolio/risk | Fractional Kelly, correlation-aware exposure, capital, drawdown and uncertainty limits, no-trade gates | Automated negative and boundary tests; independent approval records |
| Autonomous agent | Persistent planning, bounded tool use, memory, evidence challenge, monitor/reassess loop | Full decision trace; no signing access; agent cannot alter hard limits |
| Execution/reconciliation | Paper, shadow, isolated gateway, idempotency, partial fills, cancels, reconciliation, emergency stop | Paper lifecycle tests; no live order can bypass risk |
| Dashboard | Private owner console, system/session state, markets, wallets, forecasts, opportunities, positions, audit, settings | Authentication and role/permission tests |
| Operations | Docker deployment, Postgres, Valkey, backups, restore, metrics, tracing and alerting | Recovery drills and 12-hour uninterrupted test report |

## 4. Build phases (all are part of the complete target)

### Phase A — Foundation and contracts

- Monorepo structure, typed domain models, configuration and secret handling.
- PostgreSQL migrations and repositories; idempotent writes; append-only audit hash chain.
- FastAPI service contracts and authenticated single-owner dashboard.
- Docker Compose, health checks, logs, backup and restore scripts.

### Phase B — Venue data and wallet intelligence

- Gamma market/event discovery, CLOB order-book ingestion, Data API leaderboard and wallet activity.
- Cursor-based collection, deduplication, raw payload preservation, retry/backoff and rate-limit awareness.
- Candidate wallet registry capped at 10,000 initially; expand beyond leaderboard seeding through market activity and counterparty discovery.
- Trade reconstruction with fees, transfers, redeems, incomplete starting balances and unresolved gaps explicitly surfaced.

### Phase C — News and event intelligence

- Source connectors and licensing review for each source.
- Primary-source-first ranking, publication/observation times, claim provenance, duplicate and dependency detection.
- Entity and event extraction, event graph and exact market resolution-rule matching.

### Phase D — Quantitative intelligence

- Wallet metrics, Bayesian shrinkage, cluster bootstrap, multiple-testing correction and out-of-sample validation.
- Base-rate priors, evidence likelihood updates, statistical models and model ensemble interface.
- Forecast calibration by category, liquidity, horizon and probability band.
- Net EV, fee model, order-book depth, slippage, complete-set arbitrage verification and related-market equivalence checks.

### Phase E — Portfolio and risk

- Fractional Kelly with uncertainty haircut and maximum fraction.
- Correlation groups, event/category concentration, max market participation, daily loss and drawdown limits.
- Independent deterministic risk service. Defaults fail closed; all changes require the owner and audit capture.

### Phase F — Autonomous research agent

- Planner, evidence manager, event analyser, market mapper, wallet analyst, forecast coordinator, opportunity evaluator, risk client and learning service.
- Persistent structured memory and typed tool APIs.
- Prompt injection defence: external documents remain untrusted data; no secrets or signing tools in context.
- Agent may autonomously research, propose and paper trade within risk constraints, but cannot approve itself, change hard limits or submit live orders.

### Phase G — Paper, shadow and acceptance

- Paper broker using conservative live order-book depth; real-time quotes, fees, slippage and partial fills.
- 12-hour unattended live-data paper session with heartbeat, counters, error budget, restart detection and signed report.
- Extended prospective paper/shadow period; no look-ahead in replay; compare expected versus realised fills and forecast calibration.

### Phase H — Guarded live (separate future authorisation)

- Isolated signing boundary, least-privilege keys, allowlists, order limits, kill switch, cancel-all procedure and full reconciliation.
- Explicit venue geoblock check and independent local legal determination.
- Security review, model promotion approval, operator enablement and small-capital canary only after all criteria pass.
- This is not enabled or implemented in v0.1.

## 5. Initial configurable paper limits

These are conservative software defaults for simulated capital, not recommendations for actual investment:

| Parameter | v0.1 default |
|---|---:|
| Starting simulated bankroll | 10,000 units |
| Maximum paper order notional | 100 units |
| Maximum single-market exposure | 500 units |
| Maximum paper portfolio exposure | 2,500 units |
| Maximum daily simulated loss | 200 units |
| Maximum Kelly fraction | 2% bankroll |
| Maximum market-data age for a decision | 30 seconds |
| 12-hour session | 12 hours, UTC timestamps |

All limits are configurable. They are intentionally not mapped to live capital.

## 6. 12-hour acceptance gates

A test run can pass only if:

- The session starts, records owner/time/config and runs for 12 hours without unexplained gaps.
- API, database, cache and all required connectors show measured health.
- Market metadata and sampled order books are ingested with timestamps and recoverable failures.
- Data freshness, request failures, rate limits, duplicate counts and missing-field counts are captured.
- Wallet seeding and sample profile reconstruction run without false certainty claims.
- No forecast is presented as independently validated unless its model version and validation state are present.
- Paper orders require fresh book data, positive net EV, passing deterministic risk, verified fee assumptions and idempotency.
- Partial fills, no-fill, insufficient-cash, stale-book, duplicate-intent and kill-switch cases are exercised.
- Audit trail is complete and its hash chain verifies.
- Live execution routes are absent/disabled; no signing credential is present in API or agent containers.
- Test report, error log and end-of-run portfolio snapshot are produced.

A 12-hour operational pass is not a statistical profitability gate. Predictive-performance acceptance requires a materially larger prospective sample and confidence intervals.

## 7. Current delivery state

v0.2 extends the foundation with public read-only Polymarket adapters, PostgreSQL migration/repositories, deterministic paper risk and book-depth fills, Bayesian evidence updates, wallet average-cost reconstruction primitives, configured RSS source ingestion, directional and complete-set opportunity calculations, a constrained mean-variance portfolio-Kelly approximation, forecast preview/persistence routes, a timed live-data session controller, owner-authenticated API and private dashboard shell. The full target system remains under implementation. The current agent still does not autonomously create forecasts or paper orders; wallet/event/opportunity/portfolio modules are not yet connected into one autonomous decision lifecycle. This package is not a claim that every target subsystem is complete.
