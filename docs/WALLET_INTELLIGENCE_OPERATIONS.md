# ORACLE Wallet Intelligence — Owner Operations

This guide describes the v0.5 working endpoints. It is not a claim that the full ORACLE acceptance test is ready.

All endpoints below require the owner bearer token. Run them only against the private ORACLE instance and observe the returned counts/cursors after every batch.

## 1. Discover candidate wallets

```bash
curl --fail-with-body -X POST \
  'http://127.0.0.1:8000/v1/wallets/discover?target=5000&max_leaderboard_pages=20&max_market_pages=20' \
  -H "Authorization: Bearer ${ORACLE_API_TOKEN}"
```

The discovery run reads public leaderboard pages and current active Gamma markets. Active markets are queried by condition ID in batches of no more than 20. The returned report includes the unique registry count, wallets newly inserted by source in this run, pages read, source completion flags, cursor state indicators and errors.

Repeat in bounded batches where the target has not been reached or more source coverage is required. The target is a minimum unique-wallet count, so the final count can exceed it. If the target is reached early, a source cursor can remain paused; inspect the `leaderboard_complete` and `market_scan_complete` fields rather than assuming a complete source scan.

## 2. Inspect discovery and ingestion status

```bash
curl --fail-with-body \
  'http://127.0.0.1:8000/v1/wallets/ingestion-status' \
  -H "Authorization: Bearer ${ORACLE_API_TOKEN}"
```

Review the wallet registry total, source coverage, discovery checkpoints, trade counts, activity event counts by feed/type, activity cursor completion by feed, fee-known count, trade-history completion counts and score evidence-status totals. Each activity source has its own checkpoint per wallet.

## 3. Ingest wallet trade history

```bash
curl --fail-with-body -X POST \
  'http://127.0.0.1:8000/v1/wallets/ingest-trades?max_wallets=25&max_pages_per_wallet=20' \
  -H "Authorization: Bearer ${ORACLE_API_TOKEN}"
```

The call handles a bounded batch of wallets and pages, storing a checkpoint per wallet. Repeat calls until the status endpoint reports the desired number of terminal user-trade cursor walks. A terminal cursor means only that the queried Data API trade feed ended; it does not certify complete account economics, fee coverage or resolution history.

## 4. Ingest account activity

```bash
curl --fail-with-body -X POST \
  'http://127.0.0.1:8000/v1/wallets/ingest-activity?max_wallets=25&max_pages_per_wallet=20&page_size=1000' \
  -H "Authorization: Bearer ${ORACLE_API_TOKEN}"
```

This ingests three independent feeds for each wallet: standard activity (with deposits/withdrawals included), opt-in `TIP` rows (not in the default activity set), and combo lifecycle activity. Each feed has a separate opaque cursor checkpoint. Repeat bounded calls until the desired wallet/feed pairs have reached terminal cursors. Standard activity includes trade rows that can overlap `/v2/trades`; ORACLE archives them separately and does not add them to the reconstructed trade inventory a second time.

Amounts are stored as source-reported values. The current layer intentionally does not assign positive/negative cashflow signs or derive complete P&L, opening balances or fees from event names. Account reconciliation is a later acceptance gate.

## 5. Generate provisional evidence profiles

```bash
curl --fail-with-body -X POST \
  'http://127.0.0.1:8000/v1/wallets/score?max_wallets=100' \
  -H "Authorization: Bearer ${ORACLE_API_TOKEN}"
```

This loads persisted normalized trade rows, reconstructs the observed trade window, and stores a versioned evidence profile. The score is explicitly provisional. Missing OOS skill, closing-line value, risk-adjusted return, independent resolved-position consistency, timing and capacity remain unscored. The API does not infer a skilled-wallet label from this profile.

## Known data limitations

- The activity archive captures reported standard, TIP and combo activity fields, but does not yet reconcile them into a fully balanced USDC/token ledger or prove complete account cashflows.
- The documented v2 trade row has no per-fill fee field. `fee_known=false` is retained for such rows, so fee-adjusted P&L and related metrics are withheld.
- The code requests `start=1` for full-history time coverage and a low token-size threshold, but endpoint availability, filtering and historical coverage must still be measured on live data.
- The documented trade row has no guaranteed unique fill ID. A deterministic SHA-256 fingerprint is used; identical same-wallet fills with identical normalized attributes can collide.
- A public wallet may be a proxy wallet, a market participant, a bot, or an address that is not economically independent from another address. Wallet identity clustering remains a future evidence task.

## Acceptance-test status

The 12-hour autonomous acceptance test remains hard-locked in v0.5. Do not interpret these wallet endpoints as a completed test environment. The remaining platform gates are listed in `BUILD_STATUS_v0.5_WORKING.md` and `12_HOUR_TEST_PROTOCOL.md`.
