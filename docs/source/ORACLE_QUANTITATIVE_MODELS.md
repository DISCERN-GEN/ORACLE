# ORACLE Quantitative Models Specification

| Property | Value |
|---|---|
| Document | ORACLE_QUANTITATIVE_MODELS |
| Version | 1.0 |
| Date | 01 November 2026 |
| Status | Engineering baseline |
| Parent document | ORACLE Engineering Blueprint v1.0 |
| Scope | Wallet scoring, statistical validation, Bayesian forecasting, arbitrage, portfolio Kelly |

---

## 1. Design Principles

1. All edge estimates must be accompanied by uncertainty.
2. In-sample performance is never sufficient for capital allocation.
3. Fees, spread, slippage and market impact are first-class citizens.
4. Multiple-testing correction is mandatory when ranking large wallet universes.
5. Models are versioned; every forecast carries `model_id` + `model_version`.
6. Calibration is continuously monitored; deterioration triggers automatic exposure reduction.

---

## 2. Wallet Scoring Model

### 2.1 Component Weights (initial, configurable)

| Component | Weight | Description |
|---|---:|---|
| Out-of-sample predictive skill | 25% | Performance on data not used for selection |
| Risk-adjusted net return | 20% | After fees, spread, slippage |
| Closing-line value (CLV) | 15% | Entry quality vs later / closing prices |
| Consistency | 15% | Stability across independent events / regimes |
| Timing advantage | 10% | Ability to act before information is fully priced |
| Liquidity and capacity | 10% | Ability to scale without destroying edge |
| Data quality | 5% | Completeness and reliability of reconstruction |

### 2.2 Required Safeguards

The score must never conceal:

- Small sample sizes
- Poor historical coverage
- Extreme concentration in a few markets
- Negative out-of-sample results
- Unreliable P&L reconstruction

Implementation must surface these factors as explicit flags alongside the numeric score.

### 2.3 Statistical Validation Techniques

**Bayesian shrinkage**  
Extreme performance estimates are shrunk toward a hierarchical prior when sample sizes are small.

**Bootstrap**  
Event-level or market-cluster bootstrap that preserves dependence between related positions.

**Multiple-testing correction**  
False Discovery Rate (Benjamini–Hochberg or similar) when evaluating ~10,000 wallets.

**Out-of-sample confirmation**  
A wallet selected on window A must demonstrate skill on window B that was not used for selection.

**Regime analysis**  
Performance broken down by political, crypto, sports, economic, regulatory markets and by volatility / liquidity regimes.

**Net profitability**  
All metrics after realistic transaction costs.

---

## 3. Performance Metrics

| Metric | Definition / Purpose |
|---|---|
| Realised P&L | Closed-position profitability |
| Unrealised P&L | Mark-to-market of open positions |
| ROI | Return relative to a defined capital denominator |
| Win rate | Fraction of resolved positions that are profitable |
| Profit factor | Gross gains / gross losses |
| Maximum drawdown | Peak-to-trough equity decline |
| Average holding period | Duration statistics |
| Turnover | Trading activity relative to capital |
| Concentration | Herfindahl or similar on markets / categories |
| Closing-line value | Average edge vs later prices |
| Calibration | Predicted probability vs observed frequency |
| Consistency | Stability of edge across independent events |

---

## 4. Bayesian Forecasting Framework

### 4.1 Core Update

\[
P(H \mid E) = \frac{P(E \mid H)\, P(H)}{P(E)}
\]

- \(H\): event hypothesis  
- \(E\): new evidence  
- Independence of evidence sources must be assessed; repeated republication of the same report is not independent confirmation.

### 4.2 Ensemble Architecture

| Model | Role |
|---|---|
| Historical base-rate | Reference-class probabilities |
| Bayesian updater | Evidence integration + uncertainty |
| Statistical / feature model | Structured predictors |
| Domain-specific models | Specialist event types |
| Information extraction | News → structured evidence |
| Market benchmark | Comparison to traded prices |
| Ensemble | Weighted combination of validated components |

### 4.3 Forecast Output Contract

Every forecast must contain:

```json
{
  "market_id": "...",
  "outcome": "YES",
  "probability": 0.64,
  "lower_bound": 0.55,
  "upper_bound": 0.72,
  "confidence": 0.87,
  "model_id": "event-ensemble",
  "model_version": "1.0.0",
  "forecast_timestamp": "ISO-8601",
  "evidence_references": [],
  "invalidation_conditions": []
}
```

`confidence` is a separate statistical quantity and must not be confused with the event probability itself.

### 4.4 Evaluation Metrics

**Brier score**

\[
BS = \frac{1}{N} \sum_{i=1}^{N} (p_i - y_i)^2
\]

**Log loss**

\[
LL = -\frac{1}{N} \sum_{i=1}^{N} \bigl[ y_i \log p_i + (1-y_i)\log(1-p_i) \bigr]
\]

**Calibration**  
Events forecast at probability \(p\) should resolve YES with frequency ≈ \(p\) over sufficiently large samples.  
Dashboards must be maintained by model, category, horizon, liquidity and confidence band.

When calibration deteriorates, the system must automatically reduce exposure or suspend the affected model.

---

## 5. Mispricing & Expected Value

### 5.1 Directional Edge

For a YES contract bought at executable price \(C\):

\[
EV_{\text{gross}} = P(\text{YES}) - C
\]

Net EV deducts:

- Fees
- Half-spread / expected slippage
- Expected market impact
- Any other execution costs

### 5.2 Opportunity Classification

| Type | Description |
|---|---|
| Directional mispricing | Independent \(P\) materially above executable price |
| Reverse mispricing | Independent \(P\) materially below market valuation |
| Complete-set arbitrage | All complementary outcomes purchasable below guaranteed payout |
| Related-market arbitrage | Structural inconsistency between related contracts (requires settlement equivalence proof) |
| Temporal | Delayed adjustment after new information |
| Liquidity | Distortion caused by thin books |

Related-market discrepancies are **not** labelled guaranteed arbitrage unless payout and settlement equivalence have been verified.

---

## 6. Complete-Set Arbitrage

### 6.1 Basic Condition

For mutually exclusive, collectively exhaustive outcomes with executable asks \(c_1, c_2, \dots, c_n\):

\[
\sum c_i < 1 \quad \Rightarrow \quad \text{gross profit} = 1 - \sum c_i
\]

### 6.2 Mandatory Verification Checklist

1. Every possible outcome is covered.
2. Outcomes are mutually exclusive.
3. Tokens belong to compatible market conditions.
4. Settlement rules are compatible.
5. No omitted void / tie / cancellation outcome.
6. Sufficient depth on every leg.
7. Fees included.
8. Slippage included.
9. Minimum size / tick size respected.
10. Execution and settlement risk assessed.

### 6.3 Legging Risk

A partially filled multi-leg package is no longer a pure arbitrage. The execution engine must track residual exposure and either complete, unwind or hedge according to policy.

---

## 7. Kelly Capital Allocation

### 7.1 Binary Kelly

\[
f^* = \frac{b p - q}{b}
\]

where

- \(f^*\): optimal fraction of bankroll  
- \(b = \dfrac{1-c}{c}\) for a YES contract bought at price \(c\)  
- \(p\): estimated probability of success  
- \(q = 1-p\)

### 7.2 Fractional Kelly

Default configuration:

```text
KELLY_MULTIPLIER = 0.25
```

Actual fraction:

\[
f_{\text{actual}} = \text{KELLY_MULTIPLIER} \times f^*
\]

The multiplier is configurable and must be validated empirically.

### 7.3 Worked Example

```
Bankroll          = 10 000
Entry price c     = 0.58
Estimated p       = 0.72

b                 = (1-0.58)/0.58 ≈ 0.7241
q                 = 0.28
f*                ≈ 0.3336          (33.36 % full Kelly)
Quarter-Kelly     ≈ 0.0834          (8.34 %)
Illustrative size ≈ 834
```

(Before fees, correlation, uncertainty haircut.)

### 7.4 Portfolio Kelly & Constraints

Independent single-position Kelly calculations can produce dangerous aggregate exposure when positions share common drivers. Production sizing must consider:

- Correlated outcomes and related political / economic events
- Shared resolution authorities
- Crypto-market dependence
- Portfolio volatility and drawdown limits
- Liquidity and capital lock-up

A constrained portfolio optimiser is required; positions are not treated as independent.

### 7.5 Hard Risk Limits (configurable)

```
MAX_SINGLE_MARKET_EXPOSURE
MAX_SINGLE_EVENT_EXPOSURE
MAX_CATEGORY_EXPOSURE
MAX_DAILY_LOSS
MAX_PORTFOLIO_DRAWDOWN
MAX_ORDER_NOTIONAL
MAX_OPEN_ORDER_COUNT
MAX_MARKET_PARTICIPATION
MAX_KELLY_FRACTION
MAX_MODEL_UNCERTAINTY
```

### 7.6 No-Trade Conditions

The quantitative layer must return a reject when:

- Net expected value is insufficient after costs
- Model is outside its validated domain
- Resolution criteria are ambiguous
- Liquidity is inadequate or quotes are stale
- Portfolio exposure limits would be breached
- Evidence reliability is too low
- Risk controls are unavailable

---

## 8. Model Governance

1. Every model has a versioned card (inputs, assumptions, training window, known failure modes).
2. Prospective evaluation is mandatory before a model can influence live capital.
3. Calibration and skill metrics are monitored continuously.
4. Material degradation automatically reduces or suspends the model’s influence.
5. Human quant administrators approve promotion of models from research → paper → live influence.

---

## 9. Implementation Notes

- Preferred libraries: Polars / Pandas, NumPy, SciPy, scikit-learn, PyMC (Bayesian), DuckDB for large historical scans.
- All monetary and probability calculations use high-precision decimal / numeric types where capital is affected.
- Look-ahead bias is forbidden in any back-test or walk-forward study.
- Cost models (fees, spread, impact) must be conservative relative to observed live conditions.

---

**END OF ORACLE_QUANTITATIVE_MODELS v1.0**
