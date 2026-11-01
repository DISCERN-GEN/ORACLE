# ORACLE Source Package Review — 01 November 2026

## Source set reviewed

The original ZIP contains seven files: the 27-page Engineering Blueprint, the Database Schema, API Specification, Agent Specification, Quantitative Models, Deployment Runbook, and README. The five subsystem specifications broadly align with the PDF architecture and preserve the core invariant that probabilistic AI reasoning cannot authorize financial actions.

## Strong design decisions retained

- Separate research/reasoning from deterministic risk and execution.
- Treat wallet activity as evidence, not an instruction to copy trades.
- Reconstruct wallet economics with incomplete history and fees explicitly represented.
- Require out-of-sample evaluation, multiple-testing correction, Bayesian shrinkage and calibration monitoring.
- Base opportunity analysis on executable order-book prices and net costs.
- Require settlement equivalence before describing related markets as arbitrage.
- Use fractional sizing and portfolio-level correlation controls.
- Keep signing credentials outside agent context and use an append-only audit trail.
- Fail closed on stale data, missing evidence, risk-service failure and reconciliation discrepancies.

## Gaps resolved in the v0.1 foundation

1. Added an actual PostgreSQL initial migration based on the specified entities, with additional paper-session, paper-order, paper-fill and account-snapshot tables.
2. Added append-only trigger protection to the audit table.
3. Added a timed paper-session API and a live-data research loop.
4. Added read-only Polymarket connectors for Gamma market metadata, CLOB order books, public leaderboard data, wallet trades and the official geoblock check.
5. Added a public-book-driven paper fill simulator. It only consumes visible opposing-side depth at prices within the submitted limit; it does not invent liquidity.
6. Added deterministic risk checks for order size, Kelly notional budget, exposure, cash/inventory, data freshness, confidence, positive net EV and the kill switch.
7. Added API owner-token authentication, local-only port bindings in Compose, and a small private dashboard.
8. Added idempotency handling for paper-order attempts when PostgreSQL is available.

## v0.2 extensions

- Added Bayesian Beta-prior and independent-evidence updates, with duplicate/dependent evidence group protection and forecast persistence marked unvalidated.
- Added owner-configured HTTPS RSS/Atom ingestion with source tiers, hashes, timestamps, and storage; this is not yet a claim-extraction/event-graph pipeline.
- Added wallet average-cost reconstruction primitives with explicit incompleteness flags for unmatched sells, missing opening inventory and missing marks.
- Added directional executable-depth and complete-set evaluation primitives, requiring exact outcome coverage and settlement attestations.
- Added a bounded mean-variance portfolio-Kelly approximation and API evaluation routes.
- Improved Data API v2 cursor handling, retry-after backoff, order-book local receipt timestamps, persisted paper fills and audit-chain verification.

## Important design issues not silently carried forward

- The SQL source describes time partitioning but does not implement partition-safe primary keys. The initial migration therefore uses ordinary PostgreSQL tables and explicit time/entity indexes. Partitioning is deferred until actual volume and key design are measured.
- API v1 routes needed operational endpoints for system health, geoblock status, session start/stop/status, market data, order books, wallet seeding, paper order simulation and audit inspection.
- Numerical risk limits were named but not assigned values. Initial paper-only defaults are configurable and intentionally small; they are not suitable for real capital.
- A 12-hour test requires persisted session state, heartbeats, counts, errors and a clear completion status.
- The source package did not define a concrete forecasting model provider or LLM provider. v0.1 includes quantitative primitives and an explicit no-fabrication boundary; automated order generation remains disabled until an independently testable forecast provider and model governance are implemented.
- Fee logic is market-specific. Paper fills are rejected unless the fee schedule is declared verified; the current simulation uses an explicit configured rate and must not be mistaken for Polymarket's complete fee formula.
- The first wallet-discovery endpoint seeds from the public trader leaderboard. This is not a complete discovery strategy for 10,000 unique wallets; active-market trade/counterparty expansion and full P&L reconstruction remain required.

## Regulatory and venue boundary

Polymarket's own documentation requires applications to call `https://polymarket.com/api/geoblock` before order placement and says the platform's restricted-jurisdiction rules can differ by country and region. Its Terms of Use also prohibit use by restricted persons and prohibit VPN-based circumvention. The geoblock check is not a substitute for local legal approval.

The South African National Gambling Board states that online gambling is prohibited except for qualifying online betting with a South African-licensed bookmaker. Whether a particular prediction-market contract is legally classified as gambling, a derivative, or another regulated product requires qualified South African legal advice. Accordingly, live execution is not implemented in this deliverable and is not enabled by configuration.
