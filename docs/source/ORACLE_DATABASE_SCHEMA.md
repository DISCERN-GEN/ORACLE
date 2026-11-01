# ORACLE Database Schema Specification

| Property | Value |
|---|---|
| Document | ORACLE_DATABASE_SCHEMA |
| Version | 1.0 |
| Date | 01 November 2026 |
| Status | Engineering baseline |
| Parent document | ORACLE Engineering Blueprint v1.0 |
| Primary RDBMS | PostgreSQL 16+ |
| Time-series | TimescaleDB or native partitioning |
| Analytical | DuckDB + Parquet |

---

## 1. Design Principles

1. PostgreSQL is the system of record for all operational and financial state.
2. All monetary quantities use `NUMERIC` (never floating-point).
3. All timestamps are stored as `TIMESTAMPTZ` in UTC.
4. Soft-delete is preferred over hard-delete for audit-sensitive tables.
5. Every financial decision must be fully reconstructable from the audit trail.
6. Raw source payloads are retained in object storage; only normalised forms live in the database.
7. Schema changes are managed exclusively through versioned migrations.
8. Idempotency keys are mandatory on all order and intent tables.

---

## 2. Core Entity Relationship Overview

```
wallets 1──* wallet_trades
wallets 1──* wallet_positions
wallets 1──* wallet_scores

markets 1──* forecasts
markets 1──* opportunities
markets 1──* orderbook_snapshots
markets 1──* orders
markets 1──* fills

events 1──* claims
events *──* markets          (via market_event_links)
source_documents 1──* claims

orders 1──* fills
orders 1──1 risk_decisions

agent_memory (standalone structured memory)
audit_events (append-only)
model_versions / model_evaluations
portfolio_snapshots
```

---

## 3. Table Definitions

### 3.1 wallets

```sql
CREATE TABLE wallets (
    wallet_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address             TEXT NOT NULL UNIQUE,
    first_seen          TIMESTAMPTZ,
    last_seen           TIMESTAMPTZ,
    discovery_source    TEXT,
    activity_status     TEXT NOT NULL DEFAULT 'active'
                        CHECK (activity_status IN ('active', 'dormant', 'archived', 'flagged')),
    data_quality_score  NUMERIC(5,4) CHECK (data_quality_score BETWEEN 0 AND 1),
    historical_coverage_days INTEGER,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wallets_address ON wallets (address);
CREATE INDEX idx_wallets_activity ON wallets (activity_status);
CREATE INDEX idx_wallets_last_seen ON wallets (last_seen DESC);
```

### 3.2 wallet_trades

```sql
CREATE TABLE wallet_trades (
    trade_id            TEXT PRIMARY KEY,               -- venue or synthetic id
    wallet_id           UUID NOT NULL REFERENCES wallets(wallet_id),
    market_id           TEXT NOT NULL,
    token_id            TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    price               NUMERIC(18,8) NOT NULL,
    quantity            NUMERIC(28,8) NOT NULL,
    notional            NUMERIC(28,8) GENERATED ALWAYS AS (price * quantity) STORED,
    fee                 NUMERIC(18,8) NOT NULL DEFAULT 0,
    executed_at         TIMESTAMPTZ NOT NULL,
    source_ref          TEXT,
    is_partial_fill     BOOLEAN NOT NULL DEFAULT FALSE,
    reconstruction_notes TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_wallet_trades_wallet ON wallet_trades (wallet_id, executed_at DESC);
CREATE INDEX idx_wallet_trades_market ON wallet_trades (market_id, executed_at DESC);
CREATE INDEX idx_wallet_trades_executed ON wallet_trades (executed_at DESC);
```

### 3.3 wallet_positions

```sql
CREATE TABLE wallet_positions (
    position_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id           UUID NOT NULL REFERENCES wallets(wallet_id),
    market_id           TEXT NOT NULL,
    token_id            TEXT NOT NULL,
    quantity            NUMERIC(28,8) NOT NULL,
    average_entry_price NUMERIC(18,8),
    current_mark        NUMERIC(18,8),
    realised_pnl        NUMERIC(28,8) NOT NULL DEFAULT 0,
    unrealised_pnl      NUMERIC(28,8),
    last_update         TIMESTAMPTZ NOT NULL,
    UNIQUE (wallet_id, market_id, token_id)
);

CREATE INDEX idx_wallet_positions_wallet ON wallet_positions (wallet_id);
```

### 3.4 wallet_scores

```sql
CREATE TABLE wallet_scores (
    score_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id           UUID NOT NULL REFERENCES wallets(wallet_id),
    score_version       TEXT NOT NULL,
    overall_score       NUMERIC(6,4),
    oos_predictive_skill NUMERIC(6,4),
    risk_adjusted_return NUMERIC(6,4),
    closing_line_value  NUMERIC(6,4),
    consistency         NUMERIC(6,4),
    timing_advantage    NUMERIC(6,4),
    liquidity_capacity  NUMERIC(6,4),
    data_quality        NUMERIC(6,4),
    sample_size         INTEGER,
    statistical_confidence NUMERIC(5,4),
    strategy_classification TEXT,
    scored_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until         TIMESTAMPTZ,
    UNIQUE (wallet_id, score_version, scored_at)
);

CREATE INDEX idx_wallet_scores_wallet ON wallet_scores (wallet_id, scored_at DESC);
CREATE INDEX idx_wallet_scores_overall ON wallet_scores (overall_score DESC NULLS LAST);
```

### 3.5 markets

```sql
CREATE TABLE markets (
    market_id           TEXT PRIMARY KEY,
    condition_id        TEXT,
    question            TEXT NOT NULL,
    description         TEXT,
    rules_text          TEXT,
    rules_hash          TEXT,                          -- SHA-256 of rules_text
    category            TEXT,
    status              TEXT NOT NULL
                        CHECK (status IN ('open', 'closed', 'resolved', 'void', 'disputed')),
    outcome_labels      JSONB,                         -- ["Yes","No"] or multi-outcome
    outcome_token_ids   JSONB,
    open_time           TIMESTAMPTZ,
    close_time          TIMESTAMPTZ,
    resolution_time     TIMESTAMPTZ,
    resolved_outcome    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_markets_status ON markets (status);
CREATE INDEX idx_markets_close ON markets (close_time);
CREATE INDEX idx_markets_category ON markets (category);
```

### 3.6 orderbook_snapshots

```sql
CREATE TABLE orderbook_snapshots (
    snapshot_id         BIGSERIAL PRIMARY KEY,
    market_id           TEXT NOT NULL REFERENCES markets(market_id),
    token_id            TEXT NOT NULL,
    bids                JSONB NOT NULL,               -- [[price, size], ...]
    asks                JSONB NOT NULL,
    best_bid            NUMERIC(18,8),
    best_ask            NUMERIC(18,8),
    mid_price           NUMERIC(18,8),
    spread              NUMERIC(18,8),
    depth_usd           NUMERIC(28,8),
    sequence            BIGINT,
    captured_at         TIMESTAMPTZ NOT NULL,
    source              TEXT
);

-- Prefer hypertable if TimescaleDB is available
-- SELECT create_hypertable('orderbook_snapshots', 'captured_at');
CREATE INDEX idx_orderbook_market_time ON orderbook_snapshots (market_id, token_id, captured_at DESC);
```

### 3.7 forecasts

```sql
CREATE TABLE forecasts (
    forecast_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id           TEXT NOT NULL REFERENCES markets(market_id),
    outcome             TEXT NOT NULL,
    probability         NUMERIC(8,6) NOT NULL CHECK (probability BETWEEN 0 AND 1),
    lower_bound         NUMERIC(8,6),
    upper_bound         NUMERIC(8,6),
    confidence          NUMERIC(5,4),
    model_id            TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    input_snapshot_id   TEXT,
    evidence_references JSONB DEFAULT '[]',
    invalidation_conditions JSONB DEFAULT '[]',
    forecast_time       TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_forecasts_market ON forecasts (market_id, forecast_time DESC);
CREATE INDEX idx_forecasts_model ON forecasts (model_id, model_version);
```

### 3.8 opportunities

```sql
CREATE TABLE opportunities (
    opportunity_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id           TEXT NOT NULL,
    token_id            TEXT,
    opportunity_type    TEXT NOT NULL
                        CHECK (opportunity_type IN (
                            'directional_mispricing',
                            'reverse_mispricing',
                            'complete_set_arbitrage',
                            'related_market_arbitrage',
                            'temporal',
                            'liquidity'
                        )),
    gross_ev            NUMERIC(12,8),
    net_ev              NUMERIC(12,8),
    estimated_slippage  NUMERIC(12,8),
    kelly_fraction      NUMERIC(8,6),
    recommended_size    NUMERIC(28,8),
    risk_status         TEXT NOT NULL DEFAULT 'pending'
                        CHECK (risk_status IN ('pending', 'approved', 'rejected', 'expired')),
    decision            TEXT CHECK (decision IN ('trade', 'watch', 'reject', NULL)),
    forecast_id         UUID REFERENCES forecasts(forecast_id),
    rationale           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ
);

CREATE INDEX idx_opportunities_market ON opportunities (market_id, created_at DESC);
CREATE INDEX idx_opportunities_status ON opportunities (risk_status, decision);
```

### 3.9 risk_decisions

```sql
CREATE TABLE risk_decisions (
    risk_decision_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id      UUID REFERENCES opportunities(opportunity_id),
    decision            TEXT NOT NULL CHECK (decision IN ('approve', 'reject', 'defer')),
    max_notional        NUMERIC(28,8),
    max_kelly_fraction  NUMERIC(8,6),
    portfolio_exposure_after NUMERIC(28,8),
    checks_passed       JSONB NOT NULL DEFAULT '[]',
    checks_failed       JSONB NOT NULL DEFAULT '[]',
    operator_override   BOOLEAN NOT NULL DEFAULT FALSE,
    decided_by          TEXT NOT NULL,                 -- 'system' or operator id
    decided_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rationale           TEXT
);
```

### 3.10 orders

```sql
CREATE TABLE orders (
    internal_order_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_order_id      TEXT,
    opportunity_id      UUID REFERENCES opportunities(opportunity_id),
    risk_decision_id    UUID REFERENCES risk_decisions(risk_decision_id),
    market_id           TEXT NOT NULL,
    token_id            TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    limit_price         NUMERIC(18,8) NOT NULL,
    quantity            NUMERIC(28,8) NOT NULL,
    filled_quantity     NUMERIC(28,8) NOT NULL DEFAULT 0,
    average_fill_price  NUMERIC(18,8),
    execution_mode      TEXT NOT NULL
                        CHECK (execution_mode IN ('research', 'replay', 'paper', 'shadow', 'live')),
    order_state         TEXT NOT NULL DEFAULT 'CREATED'
                        CHECK (order_state IN (
                            'CREATED', 'POLICY_PENDING', 'APPROVED', 'SUBMITTED',
                            'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED',
                            'CANCEL_PENDING', 'CANCELLED', 'REJECTED', 'EXPIRED'
                        )),
    idempotency_key     TEXT NOT NULL UNIQUE,
    max_slippage_bps    INTEGER,
    submitted_at        TIMESTAMPTZ,
    last_state_change   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_state ON orders (order_state);
CREATE INDEX idx_orders_market ON orders (market_id, created_at DESC);
CREATE INDEX idx_orders_idempotency ON orders (idempotency_key);
```

### 3.11 fills

```sql
CREATE TABLE fills (
    fill_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    internal_order_id   UUID NOT NULL REFERENCES orders(internal_order_id),
    venue_fill_id       TEXT,
    price               NUMERIC(18,8) NOT NULL,
    quantity            NUMERIC(28,8) NOT NULL,
    fee                 NUMERIC(18,8) NOT NULL DEFAULT 0,
    filled_at           TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fills_order ON fills (internal_order_id);
```

### 3.12 events, claims, source_documents, market_event_links

```sql
CREATE TABLE source_documents (
    document_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         TEXT NOT NULL,
    source_name         TEXT,
    url                 TEXT,
    title               TEXT,
    published_at        TIMESTAMPTZ,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_hash        TEXT,
    raw_storage_key     TEXT,                          -- S3/object key
    reliability_tier    TEXT CHECK (reliability_tier IN (
                            'official_primary', 'first_party', 'established_journalism',
                            'specialist', 'social', 'anonymous', 'ai_summary'
                        )),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE events (
    event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type          TEXT,
    title               TEXT,
    description         TEXT,
    location            TEXT,
    event_time          TIMESTAMPTZ,
    confidence          NUMERIC(5,4),
    status              TEXT DEFAULT 'open',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE claims (
    claim_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            UUID REFERENCES events(event_id),
    document_id         UUID REFERENCES source_documents(document_id),
    claim_text          TEXT NOT NULL,
    polarity            TEXT,                          -- supports / contradicts / neutral
    confidence          NUMERIC(5,4),
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE market_event_links (
    link_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id           TEXT NOT NULL REFERENCES markets(market_id),
    event_id            UUID NOT NULL REFERENCES events(event_id),
    relationship        TEXT NOT NULL,                 -- AFFECTS, DEPENDS_ON, etc.
    confidence          NUMERIC(5,4),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (market_id, event_id, relationship)
);
```

### 3.13 agent_memory

```sql
CREATE TABLE agent_memory (
    memory_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_type         TEXT NOT NULL
                        CHECK (memory_type IN (
                            'wallet_performance', 'strategy_classification',
                            'event_dossier', 'market_resolution',
                            'source_reliability', 'probability_estimate',
                            'trading_decision', 'failed_prediction',
                            'strategy_performance', 'operator_instruction',
                            'model_evaluation'
                        )),
    entity_ref          TEXT,                          -- wallet_id, market_id, etc.
    content             JSONB NOT NULL,
    confidence          NUMERIC(5,4),
    source              TEXT,
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_memory_type ON agent_memory (memory_type, created_at DESC);
CREATE INDEX idx_agent_memory_entity ON agent_memory (entity_ref);
```

### 3.14 audit_events (append-only)

```sql
CREATE TABLE audit_events (
    audit_id            BIGSERIAL PRIMARY KEY,
    event_type          TEXT NOT NULL,
    actor               TEXT NOT NULL,                 -- system component or operator
    entity_type         TEXT,
    entity_id           TEXT,
    payload             JSONB NOT NULL,
    payload_hash        TEXT NOT NULL,                 -- SHA-256
    previous_hash       TEXT,                          -- chain integrity
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_created ON audit_events (created_at DESC);
CREATE INDEX idx_audit_entity ON audit_events (entity_type, entity_id);
```

### 3.15 Supporting tables

```sql
CREATE TABLE model_versions (
    model_id            TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    description         TEXT,
    parameters          JSONB,
    trained_at          TIMESTAMPTZ,
    validation_metrics  JSONB,
    is_active           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (model_id, model_version)
);

CREATE TABLE model_evaluations (
    evaluation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id            TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    evaluation_type     TEXT,                          -- brier, logloss, calibration, ...
    metric_value        NUMERIC(12,8),
    sample_size         INTEGER,
    period_start        TIMESTAMPTZ,
    period_end          TIMESTAMPTZ,
    details             JSONB,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE portfolio_snapshots (
    snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_equity        NUMERIC(28,8),
    cash                NUMERIC(28,8),
    open_exposure       NUMERIC(28,8),
    unrealised_pnl      NUMERIC(28,8),
    realised_pnl_day    NUMERIC(28,8),
    drawdown            NUMERIC(8,6),
    positions           JSONB,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE settlements (
    settlement_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id           TEXT NOT NULL,
    token_id            TEXT,
    outcome             TEXT,
    payout_per_share    NUMERIC(18,8),
    settled_at          TIMESTAMPTZ,
    source              TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 4. Partitioning Strategy

| Table | Partition Key | Strategy |
|---|---|---|
| `wallet_trades` | `executed_at` | Monthly range |
| `orderbook_snapshots` | `captured_at` | Daily or weekly (hypertable preferred) |
| `audit_events` | `created_at` | Monthly range |
| `forecasts` | `forecast_time` | Monthly range |
| `fills` | `filled_at` | Monthly range |

---

## 5. Indexing Guidelines

- Every foreign key should have a supporting index.
- High-cardinality time-series queries must use composite indexes that lead with the entity id then time.
- Avoid over-indexing write-heavy tables (`orderbook_snapshots`, `audit_events`).
- Partial indexes are preferred for status filters (e.g. open orders only).

---

## 6. Migration Rules

1. All schema changes live under `data/migrations/`.
2. Migrations are sequential, numbered, and idempotent where possible.
3. Never edit a migration that has already been applied in any shared environment.
4. Destructive changes require an explicit expand → migrate → contract sequence.
5. Every migration must include a corresponding rollback script or documented irreversible note.

---

## 7. Data Retention

| Data class | Hot retention | Cold / archive |
|---|---|---|
| Order-book snapshots | 30–90 days | Parquet in object storage |
| Raw source documents | 1 year | Object storage indefinite |
| Audit events | Indefinite (append-only) | — |
| Wallet trades | Full history | — |
| Forecasts | Full history | — |
| Paper-trading orders | 180 days | Archive |

---

## 8. Integrity & Constraints Summary

- Monetary values: `NUMERIC` only.
- Probabilities: constrained `BETWEEN 0 AND 1`.
- Order state machine enforced by application + CHECK constraints.
- Idempotency keys unique on `orders`.
- Audit chain uses content hashes + previous_hash for tamper evidence.
- No cascading deletes on financial tables; use soft status transitions.

---

**END OF ORACLE_DATABASE_SCHEMA v1.0**
