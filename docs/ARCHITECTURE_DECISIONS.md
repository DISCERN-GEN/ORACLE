# ORACLE Architecture Decisions

## ADR-001 — Private single-owner deployment

ORACLE is a private personal system for one initial owner. Do not add multi-tenant billing, public signup, SaaS controls or customer-management systems unless the owner later changes the requirement. Retain modular service boundaries and strong authentication.

## ADR-002 — Full platform target, staged engineering integration

All major subsystems are in the target build. Engineering implementation remains sequenced to keep the database, API, model and agent contracts testable. A staged build sequence is not a reduced product scope.

## ADR-003 — 12-hour first operational deployment

The first operational deployment uses real-time public market data and a simulated bankroll. No deposits, private keys, signing or venue orders. The session must record its start/end time, heartbeat, observations, errors, paper actions and final report.

## ADR-004 — No fabricated forecasts

The agent may not treat market price as an independent forecast or invent a predictive edge. Until a validated independent forecast provider is configured, ORACLE observes, scores data quality, runs quantitative diagnostics and records watch/reject. Paper order generation remains disabled by default.

## ADR-005 — Conservative paper fills

The simulator consumes only displayed opposite-side depth at prices within the order limit. It records partial/no fills. Paper fills require an explicit owner attestation of the configured fee assumption; this is not an exchange-verified fee schedule. Simulated fills are not equivalent to exchange fills.

## ADR-006 — Live money is a separately gated future capability

The v0.2 build ships no wallet signer and no live-order route. A future gateway requires independent geoblock check, local legal sign-off, security validation, model governance, reconciliation and explicit owner enablement. VPNs or other geoblock circumvention are prohibited.

## ADR-007 — Postgres is the financial source of truth

Postgres stores operational records, paper sessions and the append-only audit chain. Cache/streams are not authoritative. The first migration avoids partitioning until the team resolves partition-compatible keys against actual storage volume.
