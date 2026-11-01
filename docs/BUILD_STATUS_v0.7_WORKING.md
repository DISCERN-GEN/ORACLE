# BUILD STATUS v0.7 (working) — after v0.6.1 baseline `9121ac4`

Branch `v0.7-work`. Baseline commit is untouched. Not production-ready; no claim is made about wallet skill.

## Environment limits of this build session
PyPI and npm were unreachable (egress policy 403/DNS), so `asyncpg`, `pytest-asyncio`, `httpx`, `websockets`,
`fastapi` could not be installed. Consequences are listed under "Not executed".

## Defects found and fixed (v0.6.1 → v0.7)
| # | Defect | Fix | Regression test |
|---|--------|-----|-----------------|
| 0 | `Store` capture methods were dead code nested after `return` in `_parse_datetime`; `Store` had no `save_clob_raw_frame` etc. | Moved into class (AST-verified) | collector tests use the real method names |
| 1 | Gap start was the failure time, not the last durable frame | Anchored to last persisted frame | `test_connection_drop_records_gap_from_last_persisted_frame_and_resubscribes`, `test_database_stall_does_not_lose_gap_start` |
| 2 | Crash during a gap lost it | Gap persisted OPEN before the risky period; restart adopts orphan gaps and uses the earlier of orphan start / last frame | `test_open_gap_is_persisted_before_reconnect_and_survives_a_crash`, `test_restart_adopts_orphaned_open_gap_*`, `test_restart_after_kill_*` |
| 3 | Old snapshots stayed valid across gaps | Migration 005: per-asset validity + append-only log; invalid from gap start until a fresh full `book`; `clob_asset_valid_at()` | `tests/sql/validity_behaviour.sql` (PG16) |
| 4 | Backoff reset on every connect | Reset only after a connection lived ≥ 60 s | `test_flapping_connection_*`, `test_stable_connection_resets_failure_count` |
| 5 | Array frames duplicated payload per item | Parent row holds payload once; children reference it (migration 006) | `test_array_frame_payload_is_stored_once_*` |
| + | Reconnect implied health | Migration 006 `clob_connection_state`: reconnect = `recovering`; `healthy` only derived when no asset is invalid; cannot be set directly | `validity_behaviour.sql`, `test_connection_drop_*` |

## Executed
| Check | Result | Evidence |
|---|---|---|
| Migrations 001–006 applied twice on PostgreSQL 16.15 (local, not Docker) | 0 errors; schema dump identical after run 2 (ignoring pg_dump's random `\restrict` token); 6 versions recorded | `evidence/migrations_001_004_twice.txt`, `evidence/ci_simulation_pg16.txt` |
| Validity/health SQL functions on real PG16 | behaves as specified; log immutable | `evidence/migration_005_functional.txt`, `migration_006_functional.txt`, `tests/sql/validity_behaviour.sql` (+ negative control fails) |
| Collector fault tests (15) incl. drop, restart, DB stall, stop-in-gap, malformed, flapping | 15 pass, 30/30 repeat runs stable | `tests/test_collector_faults.py` |
| Mutation checks (16 re-introduced defects) | 16/16 caught (one test was strengthened after a mutation was only caught indirectly) | `evidence/collector_mutation_checks.txt` |
| Full suite runnable here | 63 passed, 2 collection errors (`httpx` missing) | — |
| Ruff 0.16.9 | 238 findings under ruff's broad defaults → explicit rule set pinned; safe autofixes (imports, UP) applied; remaining BLE001 reviewed as fail-visible/fail-closed and scoped per file; 0 findings | `evidence/ruff_before.txt`, `ruff_after.txt` |

## Not executed (reason)
- Store methods against a live `asyncpg` pool (asyncpg unavailable). SQL they call is exercised via psql only; the Python↔SQL glue is untested.
- Existing async tests (`test_wallet_discovery`, `test_polymarket_client`), the earlier "60 tests" figure, API against PG (WP1), `/healthz`, wallet ingest, checkpoint resume.
- Live WebSocket, subscription limits, REST reconciliation, trade timestamp precision, storage projection (no network to Polymarket verified; docs not re-checked) — WP2/WP4/WP5.
- `npm ci` / Next build (no `package-lock.json` in repo; registry unreachable), Docker build (no Docker daemon).
- GitHub Actions workflow itself (only its migration/SQL steps were simulated locally).
- WP3 reconstruction, WP6–WP12.

## Decisions for the owner
1. `ci.yml` assumes `web/package-lock.json` will be generated and committed; the frontend job fails until then.
2. Reconciliation against REST (needed to leave `recovering` for a *verified* healthy state) is WP4; today `healthy` means "every asset has a fresh full snapshot", not "reconciled".
3. 12-hour test and 60-day evaluation remain locked.
