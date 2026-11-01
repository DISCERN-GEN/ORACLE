# ORACLE Private Build — Delivery Status v0.2

**Build date:** 01 November 2026  
**Target:** Private single-owner ORACLE platform  
**Status:** Expanded engineering foundation assembled; complete target system remains under implementation.

## Verified in this environment

- Python source compilation: passed.
- Unit tests: **38 passed**.
- API import/OpenAPI generation: passed using a lightweight local `asyncpg` import stub; this validates route registration and Pydantic schemas, not database runtime.
- Quantitative primitives: expected value, Kelly, Bayesian updating, Brier score, log-loss and wallet score tests passed.
- Evidence engine: Beta prior, Bayesian likelihood-ratio update and duplicate/dependent-source rejection tests passed.
- Opportunity engine: visible-depth directional evaluation, fees, partial-depth rejection and complete-set coverage/settlement gates tested.
- Wallet reconstruction: average-cost accounting, unmatched sells and missing-mark uncertainty handling tested.
- Portfolio allocation approximation: single/total caps, symmetry and positive-semidefinite covariance checks tested.
- RSS/Atom parsing: source provenance, hash, reliability and HTTPS/private-host/embedded-credential/DTD input controls tested.
- Paper broker: visible-depth partial fills, owner fee attestation, minimum size, tick size and fee-inclusive cost-basis exposure accounting tested.
- Polymarket adapters: Data API v2 leaderboard cursor continuation, wallet-trade cursors and retry-after behavior tested with mocked HTTP responses.
- Original seven-file source package preserved under `docs/source/`.
- Build archive integrity check: passed.

## Not verified in this environment

- Docker Compose build or runtime: Docker is not installed in this execution environment.
- PostgreSQL migration, SQL integration, transactional order lifecycle or audit-chain verification against a live database: not run.
- Full FastAPI startup against PostgreSQL: not run; the local environment lacks `asyncpg` and package-network access is unavailable.
- Next.js production build: not run; npm dependencies were not installed and package-network access is unavailable. The dashboard dependency baseline is pinned to Next.js 16.4.3, React 19.3.1 and @types/react 19.3.0; install/build validation remains outstanding.
- External Polymarket API live session: adapters were tested with mocks, not end-to-end against live services in this build turn.

## Scope boundary

v0.2 is a broader, test-covered foundation but not the complete target architecture. The current agent only samples live market metadata and selected order books. Forecast previews remain unvalidated; the agent does not autonomously generate paper orders. Wallet trade reconstruction, RSS ingestion, opportunity evaluation and portfolio allocation are implemented as foundations but are not all scheduled and integrated as one autonomous loop. See `V0.2_SCOPE_AND_GAPS.md`.

## Real funds

Not enabled. No signing key code, wallet signer or live-order submission route is present. Do not deposit funds for v0.2. A full-system 12-hour acceptance run cannot yet be passed. Future live capability requires separate venue eligibility, South African legal assessment, security review, prospective model validation, end-to-end reconciliation and explicit owner approval.
