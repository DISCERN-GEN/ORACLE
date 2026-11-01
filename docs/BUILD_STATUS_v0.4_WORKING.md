# ORACLE v0.4 Working Build Status — Wallet Intelligence Increment

This is an integrated engineering increment toward the private autonomous dummy-test candidate. It is **not** a declaration that the platform is ready for the 12-hour acceptance test. The API and dashboard keep the 12-hour start action hard-locked until a later build passes all acceptance gates.

## Added in v0.4 working increment

### Multi-source wallet discovery
- Added a resumable discovery service using the public trader leaderboard and the trade feed for currently active Gamma markets.
- Valid EVM proxy-wallet addresses are normalized and deduplicated by the wallet registry.
- Market trade requests are batched at no more than 20 condition IDs per request, matching the documented Data API v2 request contract.
- Leaderboard cursors and active-market page offsets / pending condition batches / market-trade cursors are persisted in PostgreSQL.
- Added discovery source provenance rows so a wallet can be linked to multiple discovery sources.
- The target remains configurable up to 10,000; the default discovery target is 5,000. Pages are processed atomically from the checkpoint perspective, so the final count may exceed the target by a page-sized increment.

### Wallet trade-history ingestion
- Added per-wallet full-history retrieval using `start=1`, opaque cursor pagination and maker+taker rows (`taker_only=false`).
- Added a resumable per-wallet cursor checkpoint and idempotent normalized persistence into `wallet_trades`.
- User-scoped requests specify the full-history start sentinel (`start=1`), include maker rows, and lower the token-size filter to `0.00000001`; this reduces default dust filtering but does not establish that the API exposes every possible fill.
- Raw public trade rows and normalized-row fingerprint provenance are retained for audit/review.
- Public v2 trade rows do not document a per-fill fee. The migration adds `fee_known`; missing fees remain unknown and are not converted into a fee-adjusted zero. The reconstruction layer withholds fee-adjusted P&L, win rate and profit factor where fees are incomplete.
- Added `/v1/wallets/ingestion-status` for registry, source, trade, score and checkpoint counts.

### Provisional database-backed scoring
- Added a bounded scoring endpoint that loads persisted trade rows, reconstructs a wallet's observed trade-window inventory and writes a versioned score record.
- The pipeline intentionally does not attest initial inventory or complete account economics merely because the trade-feed cursor ended.
- The consistency component now requires explicit wins from an independent resolved-position sample; it is no longer inferred from matched sell outcomes.
- Score records persist evidence status, observed-weight coverage and warnings. The output is a provisional profile, not a skilled-wallet ranking.

### Database migration
- Added idempotent forward migration `sql/002_wallet_intelligence.sql`.
- The API applies this migration at startup after verifying the original `001_initial` schema.
- The API image now includes the `sql/` directory so the migration is available in the container.

## Acceptance-test lock

- `AUTONOMOUS_ACCEPTANCE_TEST_READY` is hard-coded `False` in this build.
- `/v1/system` exposes the locked/readiness state.
- `POST /v1/paper/session/start` returns HTTP 409 while locked.
- The dashboard start control is disabled, and `scripts/start-12h-test.sh` exits with a lock notice.
- This is intentional: v0.4 is not the autonomous dummy-test candidate.

## New owner-authenticated endpoints

- `POST /v1/wallets/discover?target=5000&max_leaderboard_pages=100&max_market_pages=100`
- `POST /v1/wallets/ingest-trades?max_wallets=25&max_pages_per_wallet=20`
- `GET /v1/wallets/ingestion-status`
- `POST /v1/wallets/score?max_wallets=100`

Discovery and ingestion are deliberately bounded and resumable. Inspect the registry count, source counts, checkpoint cursors and errors after each batch. A discovery source may be paused early when the unique-wallet target has already been reached; this is not the same as scanning that entire source to exhaustion. Repeat calls as needed to obtain more source coverage. An API timeout or endpoint failure must not be interpreted as a successful complete scan.

## Validation performed

- Python compilation: passed.
- Unit tests: **47 passed**.
- Added tests cover two-source discovery, resumable opaque cursors, full-history wallet trade ingestion, fee-unknown handling, and malformed public trade rows.
- The existing core wallet accounting, opportunity, risk and paper tests remain passing.

## Not verified in this environment

- PostgreSQL migration execution against a running PostgreSQL 16 service.
- Docker image build / Docker Compose configuration (Docker is not installed in the build environment).
- Live Polymarket Data API request behaviour, current rate-limit characteristics or the achieved 5,000-wallet result.
- Full historical trade coverage / reconciliation for 5,000 wallets.
- Inclusion of wallet transfers, redemptions, rewards, deposits, withdrawals, rebates, fee schedules and opening balances. The present wallet trade history ingestion is trade-feed only.

## Important limitations

- The source feed's documented trade shape does not provide a guaranteed unique trade identifier. ORACLE creates a deterministic SHA-256 fingerprint from normalized fields and the available transaction hash. This is stable for idempotent retries, but identical same-wallet fills with identical normalized fields may collide. This limitation is retained in raw provenance and must be addressed if a canonical sequence/id field becomes available.
- A completed trade cursor walk means the public trade endpoint pagination terminated; it does **not** prove complete account economics or complete lifetime activity.
- Fee-unknown records cannot be promoted as net P&L evidence. The current scoring module is not yet connected to the persisted ingestion pipeline.
- The discovery endpoint does not establish that every wallet has enough data for a skill judgement.

## Next engineering gate

1. Reconcile non-trade account activity (transfers, redemptions, rewards, deposits/withdrawals), opening inventory, fee schedules, open marks and resolution outcomes.
2. Add independent wallet validation metrics (chronological out-of-sample predictive skill, CLV, risk-adjusted return, strategy capacity and correlated-event controls); do not infer missing dimensions.
3. Implement automated market WebSocket ingestion plus REST reconciliation and raw market-data checkpointing.
4. Continue the forecast, opportunity, risk and autonomous paper-execution milestones in `V0.3_AUTONOMOUS_DUMMY_BUILD_PLAN.md`.

**Status:** useful wallet-intelligence increment, **not** an autonomous dummy-test candidate and **not** ready for the 12-hour test.
