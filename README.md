# ORACLE — Private Platform Build v0.6 working

**Private, single-owner prediction-market intelligence and paper-execution platform.**

This is the fifth working engineering increment based on the original ORACLE Engineering Specification Package v1.0. The complete source documents are preserved under `docs/source/`.

## Safety status

- Public Polymarket market data: read-only adapters are included.
- Wallet signing: not included.
- Real-money order submission: not included.
- Initial execution mode: simulated paper only.
- 12-hour live-data acceptance protocol: documented but locked; no autonomous test is currently authorized.
- LLM provider: optional and not configured by default.
- Forecast status: quantitative primitives exist; no independent forecast model is promoted by default.

**Do not deposit funds for this build.** A 12-hour operational pass is not proof of predictive skill, profitability, arbitrage or legal permission.

## Technology

- Python 3.12+, FastAPI, asyncpg, HTTPX
- PostgreSQL 16, Valkey 8
- Next.js 16.4.3 / React 19.3.1 / React types 19.3.0 dashboard
- Docker Compose for local private deployment

## Quick start

1. Install Docker Engine and Docker Compose on a Linux host.
2. Generate a private `.env` with unique secrets:

```bash
./scripts/init-env.sh
```

3. Review `.env`, keep it private, and start the stack:

```bash
./scripts/start.sh
```

4. Open `http://localhost:3000` and paste the `ORACLE_API_TOKEN` from `.env` into the owner-token field.
5. Confirm the system reports `PAPER ONLY` and live execution disabled.
6. Test public data access and inspect the geoblock response.
7. The 12-hour autonomous acceptance test is intentionally locked in this working build. Do not provision permanent hosting or start the acceptance run until every gate in `docs/12_HOUR_TEST_PROTOCOL.md` has passed.

API documentation is available at `http://localhost:8000/docs`; protected routes require the bearer token.

## API endpoints in v0.6 working build

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Infrastructure health |
| `GET /v1/system` | Owner system state and paper account |
| `GET /v1/geoblock` | Official Polymarket geoblock check (fail-closed on error) |
| `GET /v1/markets` | Live Gamma market metadata |
| `GET /v1/markets/{market_id}` | Market rules and metadata |
| `GET /v1/orderbooks/{token_id}` | Current CLOB order book |
| `POST /v1/news/ingest` | Ingest one owner-configured HTTPS RSS/Atom source |
| `GET /v1/news/documents` | Retrieve stored source documents and provenance |
| `POST /v1/forecasts/preview` | Bayesian prior/evidence calculation (always unvalidated) |
| `POST /v1/forecasts` | Persist an unvalidated forecast record |
| `POST /v1/opportunities/evaluate` | Evaluate directional edge against visible order-book depth |
| `POST /v1/portfolio/allocate` | Constrained mean-variance Kelly approximation |
| `GET /v1/wallets/leaderboard` | Public trader leaderboard |
| `POST /v1/wallets/discover?target=5000` | Resumable leaderboard + active-market trade wallet discovery |
| `POST /v1/wallets/ingest-trades` | Resumable full-history trade ingestion by wallet |
| `POST /v1/wallets/ingest-activity` | Resumable standard, TIP and combo activity ingestion by wallet |
| `POST /v1/wallets/score` | Persist provisional evidence profiles from reconstructed trade histories |
| `GET /v1/wallets/ingestion-status` | Registry, source, trade, score and checkpoint coverage |
| `POST /v1/paper/session/start` | Timed paper session endpoint (currently hard-locked; returns 409) |
| `GET /v1/paper/session` | Paper session and simulated account status |
| `POST /v1/paper/session/stop` | Stop a paper session |
| `POST /v1/paper/orders` | Simulate an order against visible depth after risk approval |
| `POST /v1/risk/kill-switch` | Stop paper order approvals |
| `GET /v1/audit` | Inspect latest audit events |
| `GET /v1/audit/verify` | Verify the append-only audit hash chain |

## Developer verification

```bash
python -m pip install -e '.[test]'
./scripts/verify.sh
```

For local unit tests, Docker/PostgreSQL is not required. Database integration, API startup and web build need their corresponding services/dependencies installed.

## 12-hour acceptance test — currently locked

Do not call `POST /v1/paper/session/start` in this working build. The endpoint deliberately returns HTTP 409 until all full-system acceptance gates pass. The later target test uses a 10,000-unit simulated bankroll, but it has not been run. The current observation controller samples live market metadata and selected order books; it does not autonomously generate forecasts or paper trades. The forecast/evidence, wallet and event analysis, opportunity evaluation and portfolio allocation modules remain foundations rather than a fully integrated persistent agent decision loop. No hosted server should be purchased and no 12-hour run should begin until `docs/BUILD_STATUS_v0.6_WORKING.md` and `docs/12_HOUR_TEST_PROTOCOL.md` gates pass.

## Wallet discovery and ingestion note

The v0.6 working increment extends the v0.4 wallet registry and trade-history work with per-wallet account activity ingestion. It captures the standard `/v2/activity` feed with deposits/withdrawals included, separately opts in to `TIP` rows (which are excluded by default), and ingests the `/v2/activity/combos` lifecycle feed. Every feed has an independent opaque cursor checkpoint. Standard activity rows may overlap trade-feed rows, but are archived separately and are not double-counted in trade inventory.

Activity fields are retained as reported; ORACLE does not infer cashflow direction, opening capital, realized P&L or fees from type labels or missing fields. Combo activity is likewise kept separate from base-market trade fills. The public trade feed still does not document a guaranteed per-fill fee field. Missing fees remain unknown, and provisional wallet scores still leave unsupported skill dimensions unscored. A terminal activity cursor is not proof that all historical account economics have been reconciled. See `docs/BUILD_STATUS_v0.6_WORKING.md`.

## Deployment and source docs

- `docs/IMPLEMENTATION_PLAN_v1.1.md` — consolidated complete-system plan
- `docs/SOURCE_PACKAGE_REVIEW.md` — source package review and gaps
- `docs/12_HOUR_TEST_PROTOCOL.md` — full-system acceptance test definition (not yet passable by v0.6)
- `docs/V0.2_SCOPE_AND_GAPS.md` — original v0.2 scope and outstanding integration work
- `docs/BUILD_STATUS_v0.6_WORKING.md` — current v0.6 wallet activity increment and verification boundary
- `docs/BUILD_STATUS_v0.4_WORKING.md` — previous wallet discovery and trade ingestion increment
- `docs/WALLET_INTELLIGENCE_OPERATIONS.md` — bounded wallet discovery, trade/activity ingestion and provisional scoring endpoints
- `docs/test-results-v0.6-working.txt` — current local validation record
- `docs/BUILD_STATUS_v0.2.md` — verification and environment limitations
- `docs/ARCHITECTURE_DECISIONS.md` — agreed engineering decisions
- `docs/source/` — original source package documents
- `sql/001_initial.sql` — initial PostgreSQL schema
- `sql/002_wallet_intelligence.sql` — forward migration for discovery sources, trade fee provenance and ingestion checkpoints
- `sql/003_wallet_activity.sql` — forward migration for standard and combo activity archive
- `tests/` — quantitative, paper-fill, risk and session tests

## Important database note

The initial SQL schema is mounted by Postgres only when it initializes an empty data volume. The API applies idempotent `002_wallet_intelligence` and `003_wallet_activity` forward migrations during startup. Never delete a production data volume to apply a schema change. Future changes must use forward migrations.


## Wallet skill evaluation and order-book capture (v0.6)

Read `docs/WALLET_SKILL_EVALUATION_PROTOCOL_v1.md` before interpreting wallet scores. It defines a frozen cohort, prospective selection and holdout windows, multiple-testing correction and executable-copy criteria. The protocol is registered as a design only; no prospective evaluation has been run.

Migration `sql/004_orderbook_capture.sql` stores raw public CLOB market-channel messages and full book snapshots. After applying migrations and configuring `DATABASE_URL`, the collector can be run with `ASSET_IDS` set to comma-separated outcome token IDs:

```bash
ASSET_IDS=token_id_1,token_id_2 python scripts/capture-orderbooks.py
```

This is a capture primitive, not yet a supervised production collector. Incremental `price_change` reconstruction, reconnect gap closure, REST reconciliation and live database validation remain required. Only full, valid snapshots can currently qualify for copyability matching.
