# ORACLE v0.6 working build status

**Status: research-protocol and prospective-capture increment. Not ready for the 12-hour acceptance test.**

## Changes from v0.5

1. Added `docs/WALLET_SKILL_EVALUATION_PROTOCOL_v1.md`, predeclaring the cohort freeze, 30-day selection period, 30-day holdout, primary null, copyability model, 1-second primary reaction delay, event-cluster uncertainty, BH FDR q=0.05 and minimum evidence gates.
2. Added `sql/004_orderbook_capture.sql` with raw CLOB message, full snapshot and capture-gap tables.
3. Added `oracle_platform/book_capture.py` for strict event/snapshot normalization and exact-token/time-tolerance copy-scorability checks.
4. Added persistence for raw messages and full book snapshots in `Store`.
5. Added `scripts/capture-orderbooks.py`, a public unauthenticated market-channel collector for explicitly supplied asset IDs. The v0.6 collector archived raw socket frames only after JSON decoding and had no reconnect loop; those defects are corrected in this follow-up increment below.
6. API startup now applies and verifies migration `004_orderbook_capture`.
7. Added tests for normalization, malformed levels, unknown event types, exact token matching and snapshot time tolerance.

## Test evidence

- `python -m compileall -q oracle_platform scripts`: passed.
- `python -m pytest -q`: 60 passed after capture reliability fixes.
- Docker/Compose smoke test: not run; Docker executable is unavailable in this environment.
- PostgreSQL migration/live persistence: not run; no PostgreSQL service is available here.
- Frontend npm install/build: attempted but timed out before dependencies were installed; no production build result is claimed.
- External live WebSocket capture: not run; no sustained runtime or database service available.

## Next blockers

- Run migration 004 against a disposable PostgreSQL 16 instance and verify inserts, indexes, restart and retention behaviour.
- Run Docker Compose build and health checks on a Docker-enabled host.
- Generate and commit a reproducible npm lockfile; run `npm ci` and `npm run build` in the container image.
- Run capture against a small, explicitly selected set of active token IDs; verify full snapshot arrival, event parsing, reconnect gap marking and REST reconciliation before broadening subscriptions.
- Implement validated incremental order-book reconstruction from `price_change` messages. Until then, only full `book` snapshots are eligible for copyability scoring; deltas are archived raw but must not be treated as a reconstructed book.
- Verify the revised raw-first collector and gap records against PostgreSQL and a live socket; these integration checks remain unrun in this environment.
- Build cohort manifests and prospective wallet-to-book matching; the 5,000-wallet cohort and 60-day evaluation have not started.
- Add statistical implementation for event-cluster bootstrap, matched benchmark, BH/BY corrections and predeclared scoring gates; protocol is specified but not yet computed by application code.

## Safety state

No signing code, private keys, deposits or live order execution added. Existing 12-hour acceptance route remains hard-locked. Paper-only scope is unchanged.

## Frontend version review

The existing exact pins `next@16.4.3`, `react@19.3.1` and `react-dom@19.3.1` are published registry versions as of 2026-11-01. This confirms the version strings exist; it does **not** confirm dependency compatibility or a successful local production build. The attempted npm install timed out before a lockfile or node_modules tree was produced. The build remains unverified.

## v0.6.1 capture reliability corrections

- Socket frames are persisted before JSON decoding. Plain-text keepalives, malformed JSON, non-object frames and unknown event types are retained with parser/invalidation metadata rather than terminating capture.
- Collector reconnects with bounded exponential backoff and writes a `clob_capture_gaps` row when connectivity resumes or the process stops during a gap.
- Monotonic receipt timestamps are persisted on raw message rows and full snapshots.
- `is_copy_scorable` now rejects any book timestamp after the wallet trade; it uses one-sided pre-trade age rather than absolute time distance.
- Protocol amended before cohort freeze to require one-sided pre-trade matching, explicit timestamp-resolution calibration, a deterministic matched-control construction, pre-run power analysis and measured subscription/storage qualification.
- These changes are unit-tested but have not yet been integration-tested against PostgreSQL or the live Polymarket WebSocket.
