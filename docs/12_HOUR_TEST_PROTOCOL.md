# ORACLE 12-Hour Live-Data / Dummy-Account Acceptance Protocol

**Status: target acceptance protocol. The v0.5 working build does not yet satisfy every gate below; the test start route is hard-locked.**

## Purpose

Exercise the fully integrated ORACLE platform for 12 continuous hours using current public market data and a simulated bankroll. This is a no-deposit, no-wallet, no-real-order test. The word `live` refers to live data, not live capital.

## Required session behaviour

- Default simulated bankroll: 10,000 units (configurable).
- Default duration: exactly 12 hours from recorded UTC start time.
- Session states: running → completed, or stopped/failed.
- Continuous ingestion of market, order-book, wallet and event evidence, with health/freshness metrics.
- Independent forecast generation only from approved, versioned models. Market prices and AI summaries are not independent forecasts.
- Autonomous research and paper-only trade proposals through deterministic risk approval.
- Paper execution must use executable book depth, limit prices, venue min size/tick size, verified fee assumptions and conservative partial fills.
- Session heartbeats, errors, observations, order intents, fills, account snapshots and audit-chain records persisted.
- Any restart or unresolved state reconciliation fails the run; never silently resume stale in-memory account state.

## Pre-flight gates

1. Database and migration version verified; backups and restore procedure tested.
2. Private API authentication enabled and secrets rotated from examples.
3. Live execution and wallet signing absent; no signing credentials mounted in any service.
4. Geoblock result captured for information only; local legal eligibility separately reviewed before any future live capital.
5. Data sources and access terms recorded; rate limits and retry behaviour measured.
6. All core engines and monitoring services healthy.

## Required negative and boundary tests

- Stale order book; malformed or missing market rules; unresolved market status.
- Negative/zero net EV; out-of-domain or unvalidated model; incomplete evidence.
- Inadequate liquidity/depth; partial fill; no fill; min-size/tick-size violation.
- Unverified fees; duplicate idempotency key; insufficient cash/inventory.
- Single-market/event/category/portfolio limit and daily-loss/drawdown limit.
- Kill switch and recovery/reconciliation failure.
- Contradictory source evidence and prompt-injection content in external documents.

## Pass criteria

- Full 12-hour duration reached with all heartbeats accounted for and all outages explained.
- Data freshness, gaps, retries, rate limits, duplicates and source completeness measured.
- Wallet reconstruction and ranking carry sample-size, uncertainty and out-of-sample evidence.
- Forecasts are versioned and pass predeclared calibration requirements.
- Opportunity and arbitrage calculations account for costs, executable depth and settlement semantics.
- Every paper order has a complete forecast/evidence/risk/intent/fill trace.
- Every simulated fill is consistent with recorded opposing-side liquidity; no assumed unseen depth.
- Negative tests fail closed; no duplicated or unreconciled simulated orders.
- Audit-chain verification succeeds; end-of-run portfolio and exception report produced.
- Zero real-money order submissions and zero signing-key exposure.

## Interpretation

A 12-hour pass confirms operational continuity only. It does not establish a profitable edge, reliable model calibration, guaranteed arbitrage or legal permission. Separate prospective statistical, security, venue and legal gates are mandatory before any real-funds decision.

## Current v0.5 working-build limitation

The current agent still samples open-market metadata and selected CLOB order books; it does not yet run a fully integrated autonomous decision and execution lifecycle. Wallet discovery, trade-history ingestion and provisional evidence profiles have been added, but the 5,000-wallet coverage, complete account reconciliation, independent forecast validation, event-aware portfolio controls, autonomous order generation, restart recovery and full observability gates remain unpassed. Therefore, do not classify any v0.5 observation as passing this complete-system protocol.
