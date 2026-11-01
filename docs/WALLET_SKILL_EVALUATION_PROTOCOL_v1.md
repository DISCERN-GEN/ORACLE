# ORACLE Wallet Skill Evaluation Protocol v1.0

**Protocol status:** pre-registered design; not yet executed.  
**Cohort:** up to 5,000 eligible public wallets, frozen before the prospective observation window.  
**Capital:** simulated only. No signing, deposits, live orders or wallet credentials.

## 1. Research question and null

**Question:** after a fixed selection period, do wallets selected using only information available before the holdout demonstrate repeatable, statistically unusual net trading performance, and could an independent observer have copied their observed trades using contemporaneous public order-book liquidity?

**Primary null (per wallet):** the wallet's prospective net return after executable-copy costs is no better than a predeclared no-skill benchmark conditional on market, event, side, trade time and available liquidity. A positive raw P&L or leaderboard rank is not evidence against this null.

The benchmark is a predeclared matched cohort of non-cohort wallet trades, selected without looking at subsequent outcomes. Matching is exact on outcome token and side; then on the same event/condition; then within a 15-minute UTC trade-time bucket. Among eligible controls, choose the nearest trade timestamp, breaking ties by ascending stable trade ID. Exclude the focal wallet and all wallets selected into the frozen cohort from the control pool. Require at least 5 distinct control wallets; otherwise the focal trade is unscorable for the matched comparison. Apply the same decision-time book eligibility and copy-delay execution simulation to controls. Freeze control eligibility and matching code before selection-window results are inspected. Report both the matched benchmark and a simple no-trade cash baseline.

## 2. Cohort and chronology

- **Day 0:** freeze the candidate cohort (target 5,000 unique, valid addresses) and publish a cohort manifest containing address, discovery sources, inclusion/exclusion reason, timestamp and protocol/code version. The actual count is reported; never pad to target.
- **Selection window:** days 1–30. Compute candidate features only from data timestamped within this window and pre-Day-1 public history explicitly labelled as historical context. Historical context may describe activity but cannot substitute for prospective execution evidence.
- **Freeze:** at the end of day 30, freeze ranking, thresholds, exclusions, model version and the list of wallets eligible for holdout. Hash and audit the manifest.
- **Holdout window:** days 31–60. No wallet additions, threshold tuning, weight changes or retrospective feature changes. Newly discovered wallets are held for a later cohort.
- **Minimum extension:** if the holdout contains too few resolved/markable independent events, extend only by a predeclared fixed 30-day block; do not stop early because results look good.

All timestamps are UTC. Wallets with insufficient observations remain `insufficient_evidence`; they are not silently dropped from cohort-flow reporting.

## 3. Selection and survivorship controls

- Cohort discovery combines leaderboard and active-market trade activity. Record the source and timestamp for every inclusion; leaderboard presence alone is not an eligibility criterion.
- Freeze the cohort before prospective scoring. Include inactive, delisted, losing and subsequently dormant cohort members in attrition reporting.
- Never select on holdout outcomes. Never use current leaderboard rank as a holdout feature.
- Report missingness, API coverage, incomplete trade histories and wallet attrition by source and time period.

## 4. Primary outcome and copyability

For each observed wallet trade, link only to the latest valid captured book state for the exact outcome token and market whose venue timestamp is at or before the wallet trade timestamp. A book observed after the wallet trade is never eligible, even if it is closer in absolute time. Record venue timestamp, local receive UTC and monotonic timestamps, clock offset/uncertainty, book hash, full visible depth, best bid/ask, spread, market rules and one-sided book age at the trade timestamp. If wallet timestamps are only second-resolution, the primary matching tolerance must be calibrated from live payload evidence before cohort freeze; do not imply millisecond precision the source does not provide.

A trade is copy-scorable only when:
- the exact token and market mapping is unambiguous;
- the book is a complete snapshot or a validated reconstructed state with no detected sequence gap;
- the book timestamp is at or before the wallet trade timestamp and no more than 1 second old (sensitivity analyses at 250 ms and 2 s, subject to the observed timestamp resolution);
- visible opposing-side depth supports the simulated copy quantity;
- tick size, minimum size, fees and applicable market rules are known or conservatively bounded.

First establish the book state at wallet-trade time using the latest valid pre-trade state. Then simulate copy entry against the subsequently observed book state at the declared reaction delay of 250 ms, 1 s and 3 s (primary: 1 s), walking the actual opposing-side depth. Do not use a future book to describe the wallet's decision-time information set. Include fees, spread, slippage and partial/no-fill outcomes. Do not assume the wallet's own fill price was available to the copier. Report capacity curves at fixed copy sizes and as a fraction of observed displayed depth.

The primary holdout endpoint is net copyable return per unit of committed simulated capital at the primary 1-second delay, aggregated at the wallet level with event clustering. Secondary endpoints: raw wallet return where reconstructable, Brier/log-loss for directional forecasts if available, copy fill rate, adverse selection, capacity, drawdown, turnover and sensitivity to delay/book-age thresholds.

If public trade rows do not expose a reliable wallet fill timestamp or a matching book state, that trade is unscorable. Do not substitute a later REST snapshot and call it contemporaneous.

## 5. Multiple testing and uncertainty

- Family-wise discovery is controlled with Benjamini–Hochberg false-discovery-rate (FDR) at **q = 0.05** across all 5,000 pre-registered wallet hypotheses. Report raw p-values, adjusted q-values and the number tested; use a conservative dependence-robust Benjamini–Yekutieli sensitivity analysis.
- P-values are computed from event/market-clustered resampling, not independent-trade assumptions. Resample event clusters and preserve chronology within each cluster.
- Report 95% confidence intervals, effective independent event count, trade count, resolved/markable count, coverage and missingness.
- A wallet cannot be labelled `statistically_skilled` unless it has at least 30 independent event clusters, at least 100 copy-scorable holdout trades, positive net copyable return, a positive lower 95% confidence bound, BH q < 0.05, and positive performance under the 1-second primary delay. These are minimum evidence gates, not proof of permanent skill.
- If the data do not support a valid null distribution or the required independent clusters, report `not_testable`; do not manufacture a p-value.

## 6. Required order-book capture

Capture public CLOB market-channel messages for the exact asset IDs of cohort trades and actively monitored markets. Persist raw messages before parsing, with connection ID, subscription set, local receive UTC/nanotime, venue timestamp, message type, asset ID, market/condition ID, book hash, payload and parser version. Store full `book` snapshots and every `price_change`, `tick_size_change`, `last_trade_price` and relevant lifecycle message.

A reconstructed book becomes invalid after disconnect, parser error, unknown message, detected sequence/hash inconsistency or missing baseline snapshot until a new full snapshot is received. Periodically reconcile reconstructed state against REST `/book`; discrepancies invalidate the affected interval and are measured. Preserve gaps explicitly.

The public market WebSocket does not identify all third-party wallet fills. Wallet activity/trade feeds remain the wallet attribution source; the book stream is independent market-state evidence.

## 7. Accounting scope for this experiment

Do not build a universal historical accounting engine before the prospective test. For the cohort and windows, retain raw trades, explicit fees when known, redemptions/resolutions, deposits/withdrawals/rewards as separately typed cashflow evidence, and end-of-window marks. If opening inventory, fee, transfer attribution or redemption data is missing, label P&L incomplete and keep the primary endpoint limited to trades whose copy execution can be independently simulated.

## 8. Decision outcomes

- `no_evidence`: insufficient coverage/sample or no positive result.
- `promising_unconfirmed`: positive holdout copyable return but one or more statistical/evidence gates fail.
- `statistically_skilled`: all predeclared minimum evidence and FDR gates pass.
- `copyable_at_test_size`: statistically_skilled plus a positive net return at the predeclared copy size and 1-second delay with adequate visible depth.

No category authorizes real-money execution. The 12-hour system test is operational, not a substitute for this 60-day prospective evaluation.

## 9. Pre-run power and capture-capacity qualification

Before cohort freeze or starting either clock, run a reproducible simulation of the complete planned test using clustered event-level dependence and the full 5,000-hypothesis BH procedure. Publish power curves over a predeclared grid of true net copyable edge sizes, event-cluster counts, trades per wallet, scorable-book coverage, cross-wallet correlation and attrition. Report the minimum detectable effect at 80% and 90% power; if the proposed gates make modest effects practically undetectable, revise the design as a new protocol version before collection begins. Do not weaken thresholds after holdout outcomes are visible.

Before the 60-day run, measure the actual WebSocket subscription limit, reconnect/resubscribe behaviour, maximum practical asset subscription count and raw-message storage rate on a representative active-market sample. Extrapolate daily and 60-day storage with indexes/WAL overhead and a safety factor. Do not assume that a 5,000-wallet cohort maps to 5,000 assets: the required market universe must be discovered and subscribed using measured provider limits. Capture coverage and dropped/invalidated intervals are primary experiment diagnostics.

## 10. Deviations

Any deviation is timestamped, reasoned and audited. A material change to cohort, outcome, null, windows, copy delay, FDR method or thresholds creates a new protocol version and a new cohort; do not rewrite the registered protocol after observing holdout results.
