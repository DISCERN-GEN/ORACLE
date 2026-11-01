# ORACLE v0.5 Working Build Status — Wallet Activity Archive

This is the next integrated increment toward the private autonomous dummy-test candidate. It is **not** a declaration that the platform is ready for the 12-hour acceptance test. The API and dashboard keep the acceptance-test start action hard-locked.

## Added in v0.5 working increment

### Standard wallet activity ingestion
- Added a public, read-only adapter for `GET /v2/activity`.
- User-scoped requests use `start=1` for the full available history, stable `sort_by=TIMESTAMP` / `sort_direction=DESC`, and preserve the opaque `next_cursor`.
- Explicitly sends `exclude_deposits_withdrawals=false`; the endpoint otherwise excludes those rows by default.
- Added a separate `type=TIP` walk because TIP events are opt-in and are not part of the default activity set.
- Activity source filters are held constant while each cursor is resumed.
- The shared public HTTP client applies a conservative 0.06-second minimum request interval (about 16.7 requests/second), below the documented activity-feed ceiling of 20 requests/second; `429` responses still honour `Retry-After`.

### Combo lifecycle ingestion
- Added a separate adapter for `GET /v2/activity/combos`.
- Combo actions are ingested independently from standard trade/activity rows, retaining combo condition/position IDs, action type, block/time metadata where supplied, transaction hash and event ID.
- Each wallet has an independent checkpoint for each feed: `activity`, `activity_tips` and `activity_combos`.

### Durable raw activity archive
- Added the idempotent forward migration `sql/003_wallet_activity.sql` and a `wallet_activity` table.
- Persisted normalized fields include feed, type, condition/token identifiers, side, price, share amount, USDC amount/payout fields, event time, transaction hash, source ID and the complete raw response row.
- Standard activity and combo rows are stored separately from `wallet_trades`. Standard activity can contain trade rows; these are not added a second time to reconstructed trade inventory.
- Activity source event IDs are used for combo rows where the feed documents a stable `tx_hash-log_index` ID. Standard activity uses a deterministic normalized-row fingerprint where no unique fill/event identifier is guaranteed.
- Wallet ingestion status now reports counts by activity feed and event type, completed/incomplete wallet-feed cursors and a bounded checkpoint sample.

### Accounting guardrails
- Amounts are retained as source-reported values. ORACLE does **not** infer deposit/withdrawal signs, opening capital, cashflow direction, realized P&L, fees or profitability from event type names or missing fields.
- Unknown event types and missing numeric values remain visible in raw data and are not replaced with zero.
- The activity archive is evidence for later reconciliation. It is not yet a balanced token/USDC ledger and it does not attest account economics.

## New owner-authenticated endpoint

- `POST /v1/wallets/ingest-activity?max_wallets=25&max_pages_per_wallet=20&page_size=1000`

The existing wallet endpoints remain available:
- `POST /v1/wallets/discover`
- `POST /v1/wallets/ingest-trades`
- `GET /v1/wallets/ingestion-status`
- `POST /v1/wallets/score`

## Validation performed

- `python -m compileall -q oracle_platform tests`: passed.
- `pytest -q`: **55 passed**.
- Unit tests cover standard activity and combo adapters, opt-in TIP parameterization, event normalization, unknown/missing accounting fields, and independent cursor resumption across feeds.
- No test has been run against the live Polymarket API or a production wallet universe.

## Not verified in this environment

- PostgreSQL 16 migration execution and SQL behavior against a running database.
- Docker image / Docker Compose build and runtime.
- Next.js production build.
- Live Data API v2 behaviour for deposits/withdrawals inclusion, TIP event coverage, cursor longevity, rate limits or complete historical coverage.
- Actual source coverage or ingestion throughput for 5,000 candidate wallets.
- Complete accounting reconciliation of deposits, withdrawals, trades, split/merge/conversion/compression/wrap/unwrap, redemption/payout, tips, rewards, rebates, fees, funding, opening holdings, unresolved positions, resolutions and current marks.
- Combo-feed parity against a chain-level event indexer or canonical transaction logs.

## Important remaining limitations

- Data API activity is a public serving layer. A terminal cursor proves only that the requested feed returned no further page; it is not proof that every economically relevant on-chain event is represented or that a wallet's full starting balance is known.
- The three feed cursors are independent. Completion must be checked per wallet and per feed. A wallet is not considered fully accounted merely because one feed is complete.
- Standard activity includes trade rows that overlap the separately ingested trade feed; ORACLE intentionally stores them without using them as additional trade fills.
- Event type and amount fields are raw observations, not a substitute for accounting semantics. No signed cashflow or P&L is calculated in this increment.
- The v0.5 scoring route still creates provisional evidence profiles. It does not calculate validated chronological out-of-sample skill, CLV, independent statistical consistency, complete fee-adjusted returns or sustainable capacity.

## Acceptance-test lock

- `AUTONOMOUS_ACCEPTANCE_TEST_READY` remains hard-coded `False`.
- `POST /v1/paper/session/start` remains HTTP 409 while locked.
- Dashboard control remains disabled and `scripts/start-12h-test.sh` remains locked.
- No real funds, wallet signing, deposits, or live orders are supported.

## Next engineering gate

1. Reconcile activity, trade and combo event records into a double-entry-style token/USDC ledger with source-to-chain verification, transfer handling and opening-inventory checks.
2. Retrieve and reconcile public wallet positions, resolution states, current marks and official PnL data without treating missing values as zero.
3. Establish fee schedules and rebates per market/time/role; do not impute a universal fee.
4. Build evidence-backed wallet metrics with chronological out-of-sample predictive skill, CLV, risk-adjusted return, strategy capacity, event clustering, Bayesian shrinkage and multiple-testing controls.
5. Add live market WebSocket ingestion, REST reconciliation, source archives, freshness and data-quality monitoring.
6. Complete independent forecasts, persistent research planning, autonomous paper proposal generation, deterministic risk control, order lifecycle/restart reconciliation, dashboards and full integration acceptance tests.

**Status:** wallet activity archive increment integrated and unit-tested; **not** a complete wallet accounting engine, **not** an autonomous dummy-test candidate, and **not** ready for the 12-hour test.
