-- ORACLE private platform - initial PostgreSQL migration
-- Deliberately uses ordinary PostgreSQL tables first. Partitioning is deferred until
-- observed ingestion volume justifies it; this avoids invalid partition/unique-key combinations.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS wallets (
    wallet_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address TEXT NOT NULL UNIQUE,
    first_seen TIMESTAMPTZ,
    last_seen TIMESTAMPTZ,
    discovery_source TEXT,
    activity_status TEXT NOT NULL DEFAULT 'active'
        CHECK (activity_status IN ('active','dormant','archived','flagged')),
    data_quality_score NUMERIC(5,4) CHECK (data_quality_score BETWEEN 0 AND 1),
    historical_coverage_days INTEGER CHECK (historical_coverage_days >= 0),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wallets_activity ON wallets(activity_status);
CREATE INDEX IF NOT EXISTS idx_wallets_last_seen ON wallets(last_seen DESC);

CREATE TABLE IF NOT EXISTS wallet_trades (
    trade_id TEXT PRIMARY KEY,
    wallet_id UUID NOT NULL REFERENCES wallets(wallet_id),
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    price NUMERIC(18,8) NOT NULL CHECK (price BETWEEN 0 AND 1),
    quantity NUMERIC(28,8) NOT NULL CHECK (quantity > 0),
    notional NUMERIC(28,8) GENERATED ALWAYS AS (price * quantity) STORED,
    fee NUMERIC(18,8) NOT NULL DEFAULT 0 CHECK (fee >= 0),
    executed_at TIMESTAMPTZ NOT NULL,
    source_ref TEXT,
    is_partial_fill BOOLEAN NOT NULL DEFAULT FALSE,
    reconstruction_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet_time ON wallet_trades(wallet_id, executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_market_time ON wallet_trades(market_id, executed_at DESC);

CREATE TABLE IF NOT EXISTS wallet_positions (
    position_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id UUID NOT NULL REFERENCES wallets(wallet_id),
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    quantity NUMERIC(28,8) NOT NULL,
    average_entry_price NUMERIC(18,8),
    current_mark NUMERIC(18,8),
    realised_pnl NUMERIC(28,8) NOT NULL DEFAULT 0,
    unrealised_pnl NUMERIC(28,8),
    last_update TIMESTAMPTZ NOT NULL,
    UNIQUE(wallet_id, market_id, token_id)
);
CREATE INDEX IF NOT EXISTS idx_wallet_positions_wallet ON wallet_positions(wallet_id);

CREATE TABLE IF NOT EXISTS wallet_scores (
    score_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id UUID NOT NULL REFERENCES wallets(wallet_id),
    score_version TEXT NOT NULL,
    overall_score NUMERIC(6,4),
    oos_predictive_skill NUMERIC(6,4),
    risk_adjusted_return NUMERIC(6,4),
    closing_line_value NUMERIC(6,4),
    consistency NUMERIC(6,4),
    timing_advantage NUMERIC(6,4),
    liquidity_capacity NUMERIC(6,4),
    data_quality NUMERIC(6,4),
    sample_size INTEGER CHECK(sample_size >= 0),
    statistical_confidence NUMERIC(5,4),
    strategy_classification TEXT,
    scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ,
    UNIQUE(wallet_id, score_version, scored_at)
);
CREATE INDEX IF NOT EXISTS idx_wallet_scores_wallet ON wallet_scores(wallet_id, scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_scores_overall ON wallet_scores(overall_score DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS markets (
    market_id TEXT PRIMARY KEY,
    condition_id TEXT,
    question TEXT NOT NULL,
    description TEXT,
    rules_text TEXT,
    rules_hash TEXT,
    category TEXT,
    status TEXT NOT NULL CHECK(status IN ('open','closed','resolved','void','disputed')),
    outcome_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome_token_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    open_time TIMESTAMPTZ,
    close_time TIMESTAMPTZ,
    resolution_time TIMESTAMPTZ,
    resolved_outcome TEXT,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_markets_status ON markets(status);
CREATE INDEX IF NOT EXISTS idx_markets_close ON markets(close_time);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);

CREATE TABLE IF NOT EXISTS orderbook_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    market_id TEXT NOT NULL REFERENCES markets(market_id),
    token_id TEXT NOT NULL,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL,
    best_bid NUMERIC(18,8),
    best_ask NUMERIC(18,8),
    mid_price NUMERIC(18,8),
    spread NUMERIC(18,8),
    depth_usd NUMERIC(28,8),
    sequence BIGINT,
    captured_at TIMESTAMPTZ NOT NULL,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_orderbook_market_time ON orderbook_snapshots(market_id, token_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL REFERENCES markets(market_id),
    outcome TEXT NOT NULL,
    probability NUMERIC(8,6) NOT NULL CHECK(probability BETWEEN 0 AND 1),
    lower_bound NUMERIC(8,6) CHECK(lower_bound BETWEEN 0 AND 1),
    upper_bound NUMERIC(8,6) CHECK(upper_bound BETWEEN 0 AND 1),
    confidence NUMERIC(5,4) CHECK(confidence BETWEEN 0 AND 1),
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    input_snapshot_id TEXT,
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    invalidation_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    forecast_time TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK(lower_bound IS NULL OR lower_bound <= probability),
    CHECK(upper_bound IS NULL OR probability <= upper_bound)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_market_time ON forecasts(market_id, forecast_time DESC);
CREATE INDEX IF NOT EXISTS idx_forecasts_model ON forecasts(model_id, model_version);

CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL REFERENCES markets(market_id),
    token_id TEXT,
    opportunity_type TEXT NOT NULL CHECK(opportunity_type IN (
        'directional_mispricing','reverse_mispricing','complete_set_arbitrage',
        'related_market_arbitrage','temporal','liquidity')),
    gross_ev NUMERIC(12,8),
    net_ev NUMERIC(12,8),
    estimated_slippage NUMERIC(12,8),
    kelly_fraction NUMERIC(8,6),
    recommended_size NUMERIC(28,8),
    risk_status TEXT NOT NULL DEFAULT 'pending' CHECK(risk_status IN ('pending','approved','rejected','expired')),
    decision TEXT CHECK(decision IN ('trade','watch','reject') OR decision IS NULL),
    forecast_id UUID REFERENCES forecasts(forecast_id),
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_opportunities_market_time ON opportunities(market_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(risk_status, decision);

CREATE TABLE IF NOT EXISTS risk_decisions (
    risk_decision_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id UUID REFERENCES opportunities(opportunity_id),
    decision TEXT NOT NULL CHECK(decision IN ('approve','reject','defer')),
    max_notional NUMERIC(28,8),
    max_kelly_fraction NUMERIC(8,6),
    portfolio_exposure_after NUMERIC(28,8),
    checks_passed JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks_failed JSONB NOT NULL DEFAULT '[]'::jsonb,
    operator_override BOOLEAN NOT NULL DEFAULT FALSE,
    decided_by TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rationale TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    internal_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    venue_order_id TEXT,
    opportunity_id UUID REFERENCES opportunities(opportunity_id),
    risk_decision_id UUID REFERENCES risk_decisions(risk_decision_id),
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    limit_price NUMERIC(18,8) NOT NULL CHECK(limit_price > 0 AND limit_price < 1),
    quantity NUMERIC(28,8) NOT NULL CHECK(quantity > 0),
    filled_quantity NUMERIC(28,8) NOT NULL DEFAULT 0 CHECK(filled_quantity >= 0),
    average_fill_price NUMERIC(18,8),
    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('research','replay','paper','shadow','live')),
    order_state TEXT NOT NULL DEFAULT 'CREATED' CHECK(order_state IN (
        'CREATED','POLICY_PENDING','APPROVED','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED',
        'FILLED','CANCEL_PENDING','CANCELLED','REJECTED','EXPIRED')),
    idempotency_key TEXT NOT NULL UNIQUE,
    max_slippage_bps INTEGER,
    submitted_at TIMESTAMPTZ,
    last_state_change TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(order_state);
CREATE INDEX IF NOT EXISTS idx_orders_market_time ON orders(market_id, created_at DESC);

CREATE TABLE IF NOT EXISTS fills (
    fill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    internal_order_id UUID NOT NULL REFERENCES orders(internal_order_id),
    venue_fill_id TEXT,
    price NUMERIC(18,8) NOT NULL CHECK(price > 0 AND price < 1),
    quantity NUMERIC(28,8) NOT NULL CHECK(quantity > 0),
    fee NUMERIC(18,8) NOT NULL DEFAULT 0 CHECK(fee >= 0),
    filled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(internal_order_id);

CREATE TABLE IF NOT EXISTS source_documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    source_name TEXT,
    url TEXT,
    title TEXT,
    published_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_hash TEXT UNIQUE,
    summary TEXT,
    raw_storage_key TEXT,
    reliability_tier TEXT CHECK(reliability_tier IN (
        'official_primary','first_party','established_journalism','specialist','social','anonymous','ai_summary')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT,
    title TEXT,
    description TEXT,
    location TEXT,
    event_time TIMESTAMPTZ,
    confidence NUMERIC(5,4) CHECK(confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(event_id),
    document_id UUID REFERENCES source_documents(document_id),
    claim_text TEXT NOT NULL,
    polarity TEXT CHECK(polarity IN ('supports','contradicts','neutral') OR polarity IS NULL),
    confidence NUMERIC(5,4) CHECK(confidence BETWEEN 0 AND 1),
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS market_event_links (
    link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL REFERENCES markets(market_id),
    event_id UUID NOT NULL REFERENCES events(event_id),
    relationship TEXT NOT NULL,
    confidence NUMERIC(5,4) CHECK(confidence BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(market_id, event_id, relationship)
);

CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_type TEXT NOT NULL CHECK(memory_type IN (
        'wallet_performance','strategy_classification','event_dossier','market_resolution',
        'source_reliability','probability_estimate','trading_decision','failed_prediction',
        'strategy_performance','operator_instruction','model_evaluation')),
    entity_ref TEXT,
    content JSONB NOT NULL,
    confidence NUMERIC(5,4) CHECK(confidence BETWEEN 0 AND 1),
    source TEXT,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_memory_type ON agent_memory(memory_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_memory_entity ON agent_memory(entity_ref);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    previous_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);

CREATE OR REPLACE FUNCTION oracle_reject_audit_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_audit_append_only ON audit_events;
CREATE TRIGGER trg_audit_append_only BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION oracle_reject_audit_mutation();

CREATE TABLE IF NOT EXISTS model_versions (
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    description TEXT,
    parameters JSONB,
    trained_at TIMESTAMPTZ,
    validation_metrics JSONB,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(model_id, model_version)
);

CREATE TABLE IF NOT EXISTS model_evaluations (
    evaluation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    evaluation_type TEXT,
    metric_value NUMERIC(12,8),
    sample_size INTEGER,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    details JSONB,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    total_equity NUMERIC(28,8),
    cash NUMERIC(28,8),
    open_exposure NUMERIC(28,8),
    unrealised_pnl NUMERIC(28,8),
    realised_pnl_day NUMERIC(28,8),
    drawdown NUMERIC(8,6),
    positions JSONB,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settlements (
    settlement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    market_id TEXT NOT NULL,
    token_id TEXT,
    outcome TEXT,
    payout_per_share NUMERIC(18,8),
    settled_at TIMESTAMPTZ,
    source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Operational extension: timed paper-test session, persisted across API restarts.
CREATE TABLE IF NOT EXISTS paper_sessions (
    session_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('created','running','completed','stopped','failed')),
    heartbeat_at TIMESTAMPTZ,
    observations BIGINT NOT NULL DEFAULT 0,
    orders_submitted BIGINT NOT NULL DEFAULT 0,
    errors BIGINT NOT NULL DEFAULT 0,
    initial_bankroll NUMERIC(28,8) NOT NULL CHECK(initial_bankroll > 0),
    report JSONB
);
CREATE INDEX IF NOT EXISTS idx_paper_sessions_state ON paper_sessions(state, started_at DESC);

CREATE TABLE IF NOT EXISTS paper_account_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES paper_sessions(session_id),
    account JSONB NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_paper_account_session ON paper_account_snapshots(session_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS paper_orders (
    paper_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES paper_sessions(session_id),
    idempotency_key TEXT NOT NULL UNIQUE,
    market_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
    limit_price NUMERIC(18,8) NOT NULL CHECK(limit_price > 0 AND limit_price < 1),
    quantity NUMERIC(28,8) NOT NULL CHECK(quantity > 0),
    status TEXT NOT NULL,
    request JSONB NOT NULL,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_fills (
    paper_fill_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_order_id UUID NOT NULL REFERENCES paper_orders(paper_order_id),
    price NUMERIC(18,8) NOT NULL,
    quantity NUMERIC(28,8) NOT NULL,
    fee NUMERIC(28,8) NOT NULL DEFAULT 0,
    simulated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO schema_migrations(version) VALUES('001_initial') ON CONFLICT DO NOTHING;
