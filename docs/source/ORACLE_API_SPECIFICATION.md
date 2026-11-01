# ORACLE API Specification

| Property | Value |
|---|---|
| Document | ORACLE_API_SPECIFICATION |
| Version | 1.0 |
| Date | 01 November 2026 |
| Status | Engineering baseline |
| Parent document | ORACLE Engineering Blueprint v1.0 |
| Style | REST + JSON |
| Framework target | FastAPI |
| Auth model | Service-to-service + operator RBAC |

---

## 1. Design Principles

1. All mutating endpoints require an idempotency key where retries are possible.
2. Financial actions are never authorised solely by an LLM response.
3. Every response that influences capital includes a decision trace identifier.
4. Error codes are stable strings; HTTP status codes follow conventional semantics.
5. Internal APIs are not public; network controls and authentication are mandatory.
6. Paper and live execution modes are distinguished at the intent level.

---

## 2. Common Conventions

### 2.1 Request / Response Envelope

Successful responses return the resource directly or a list wrapper:

```json
{
  "data": [ ... ],
  "meta": {
    "count": 42,
    "next_cursor": "..."
  }
}
```

Error responses:

```json
{
  "error": {
    "code": "RISK_LIMIT_EXCEEDED",
    "message": "Human readable explanation",
    "details": {},
    "trace_id": "uuid"
  }
}
```

### 2.2 Standard Headers

| Header | Required | Purpose |
|---|---|---|
| `Authorization` | Yes | Bearer token or mTLS identity |
| `X-Idempotency-Key` | On POST/PUT that mutate state | Client-generated UUID |
| `X-Request-ID` | Recommended | Correlation |
| `X-Execution-Mode` | On order intents | `paper` \| `shadow` \| `live` |

### 2.3 Stable Error Codes

```
INVALID_MARKET_RULES
STALE_QUOTE
INSUFFICIENT_DEPTH
MODEL_OUT_OF_DOMAIN
RISK_LIMIT_EXCEEDED
ELIGIBILITY_BLOCKED
DUPLICATE_INTENT
VENUE_UNAVAILABLE
RECONCILIATION_REQUIRED
MANUAL_REVIEW_REQUIRED
NOT_FOUND
VALIDATION_ERROR
UNAUTHORIZED
FORBIDDEN
```

---

## 3. Endpoint Catalogue

### 3.1 Markets

#### `GET /markets`

List markets with optional filters.

**Query parameters**

| Param | Type | Description |
|---|---|---|
| `status` | string | `open`, `closed`, `resolved`, ... |
| `category` | string | Category filter |
| `cursor` | string | Pagination |
| `limit` | int | Default 50, max 200 |

**Response** — array of market summaries.

#### `GET /markets/{market_id}`

Full market detail including rules text, outcome tokens, resolution status.

---

### 3.2 Wallets

#### `GET /wallets`

Registry of discovered wallets.

**Query parameters**: `activity_status`, `min_score`, `cursor`, `limit`

#### `POST /wallets/discover`

Trigger discovery job.

**Request body**

```json
{
  "sources": ["leaderboard", "active_markets", "counterparty"],
  "max_new_wallets": 500,
  "priority": "normal"
}
```

**Response**

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

#### `GET /wallets/{wallet_id}/profile`

Complete analytical profile (scores, metrics, classification, data quality).

#### `POST /wallets/analyse`

Request (re)analysis of one or more wallets.

**Request body**

```json
{
  "wallet_ids": ["uuid", "..."],
  "force_refresh": false,
  "score_version": "1.0"
}
```

---

### 3.3 Events & Evidence

#### `POST /events/ingest`

Ingest a normalised event or source document reference.

**Request body**

```json
{
  "source_type": "established_journalism",
  "source_name": "Reuters",
  "url": "https://...",
  "title": "...",
  "published_at": "2026-11-01T12:00:00Z",
  "content_hash": "sha256:...",
  "raw_storage_key": "s3://...",
  "extracted_claims": [
    {
      "claim_text": "...",
      "polarity": "supports",
      "confidence": 0.82
    }
  ],
  "linked_market_ids": ["market-id"]
}
```

#### `GET /events/{event_id}/evidence`

Return claims, source documents and confidence for an event.

---

### 3.4 Forecasts

#### `POST /forecasts`

Generate or record a forecast.

**Request body**

```json
{
  "market_id": "market-id",
  "outcome": "YES",
  "probability": 0.64,
  "lower_bound": 0.55,
  "upper_bound": 0.72,
  "confidence": 0.87,
  "model_id": "event-ensemble",
  "model_version": "1.0.0",
  "input_snapshot_id": "snap-...",
  "evidence_references": [],
  "invalidation_conditions": []
}
```

#### `POST /forecasts/score`

Evaluate historical forecasts (Brier, log-loss, calibration).

**Request body**

```json
{
  "model_id": "event-ensemble",
  "model_version": "1.0.0",
  "period_start": "2026-08-01T00:00:00Z",
  "period_end": "2026-11-01T00:00:00Z"
}
```

---

### 3.5 Opportunities

#### `POST /opportunities/evaluate`

Evaluate a candidate opportunity (mispricing or arbitrage).

**Request body**

```json
{
  "market_id": "market-id",
  "token_id": "token-id",
  "opportunity_type": "directional_mispricing",
  "forecast_id": "uuid",
  "executable_price": 0.58,
  "side": "BUY",
  "max_slippage_bps": 35
}
```

**Response** includes `gross_ev`, `net_ev`, `kelly_fraction`, `recommended_size`, `risk_status`.

---

### 3.6 Risk

#### `POST /risk/evaluate`

Request independent risk approval for an opportunity.

**Request body**

```json
{
  "opportunity_id": "uuid",
  "requested_notional": 834.00,
  "requested_kelly_fraction": 0.0834,
  "portfolio_context_id": "optional-snapshot-id"
}
```

**Response**

```json
{
  "risk_decision_id": "uuid",
  "decision": "approve",
  "max_notional": 834.00,
  "max_kelly_fraction": 0.0834,
  "checks_passed": ["liquidity", "exposure", "model_domain"],
  "checks_failed": [],
  "decided_at": "2026-11-01T15:00:00Z"
}
```

#### `POST /risk/kill-switch`

Emergency control.

**Request body**

```json
{
  "scope": "all" | "live_only" | "market" | "category",
  "target_id": "optional",
  "reason": "string",
  "operator_id": "string"
}
```

Requires elevated role + dual control in production.

---

### 3.7 Order Intents & Orders

#### `POST /order-intents`

Submit an approved order intent. Execution gateway performs its own validation.

**Request body**

```json
{
  "intent_id": "uuid",
  "opportunity_id": "uuid",
  "mode": "paper",
  "market_id": "market-id",
  "token_id": "token-id",
  "side": "BUY",
  "limit_price": 0.58,
  "quantity": 100,
  "max_slippage_bps": 35,
  "forecast_id": "uuid",
  "risk_decision_id": "uuid",
  "idempotency_key": "uuid"
}
```

**Response**

```json
{
  "internal_order_id": "uuid",
  "order_state": "POLICY_PENDING",
  "accepted_at": "2026-11-01T15:00:01Z"
}
```

#### `GET /orders/{internal_order_id}`

Current order state, fills and reconciliation status.

#### `POST /orders/{internal_order_id}/cancel`

Request cancellation (subject to venue and policy).

---

### 3.8 Audit & Portfolio

#### `GET /audit`

Query decision records.

**Query parameters**: `entity_type`, `entity_id`, `from`, `to`, `cursor`

#### `GET /portfolio/snapshot`

Latest or historical portfolio snapshot (equity, exposure, drawdown, positions).

---

## 4. Data Contracts (Key Types)

### MarketSummary

```json
{
  "market_id": "string",
  "question": "string",
  "status": "open",
  "category": "string",
  "close_time": "ISO-8601",
  "best_bid": 0.55,
  "best_ask": 0.57
}
```

### WalletProfile

```json
{
  "wallet_id": "uuid",
  "address": "0x...",
  "first_seen": "ISO-8601",
  "last_seen": "ISO-8601",
  "total_trades": 142,
  "resolved_events": 38,
  "realised_pnl": 1250.40,
  "estimated_roi": 0.18,
  "win_rate": 0.61,
  "profit_factor": 1.85,
  "max_drawdown": 0.12,
  "closing_line_value": 0.034,
  "oos_performance": 0.09,
  "statistical_confidence": 0.78,
  "data_completeness": 0.92,
  "strategy_classification": "directional_predictor",
  "wallet_intelligence_score": 0.74
}
```

### Forecast

```json
{
  "forecast_id": "uuid",
  "market_id": "string",
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

### OrderIntent (accepted)

```json
{
  "internal_order_id": "uuid",
  "order_state": "APPROVED",
  "execution_mode": "paper",
  "side": "BUY",
  "limit_price": 0.58,
  "quantity": 100,
  "idempotency_key": "uuid"
}
```

---

## 5. Authentication & Authorisation

| Role | Typical permissions |
|---|---|
| `viewer` | GET only |
| `research_analyst` | Research endpoints, forecasts, wallet analysis |
| `quant_admin` | Model configuration, score versions |
| `risk_operator` | Risk limits, kill-switch (with dual control) |
| `execution_operator` | Order intents in paper/shadow; live requires extra controls |
| `system` | Service-to-service internal calls |

Live-mode order submission requires:
- Valid risk decision
- Execution operator role (or system with explicit live flag)
- Kill-switch not active
- Successful policy validation inside the execution gateway

---

## 6. Versioning

- URL prefix: `/v1/`
- Breaking changes require a new major version.
- Additive fields are non-breaking.
- Deprecated fields are marked in OpenAPI and retained for at least one minor release cycle.

---

## 7. OpenAPI

An OpenAPI 3.1 document must be generated from the FastAPI application and published under `/openapi.json`.  
Contract tests in `tests/contract/` validate that the live schema matches this specification.

---

**END OF ORACLE_API_SPECIFICATION v1.0**
