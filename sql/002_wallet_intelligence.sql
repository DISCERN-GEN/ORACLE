-- Durable wallet discovery and trade-ingestion state.
-- Safe to apply to an existing 001_initial database.

ALTER TABLE wallet_trades
    ADD COLUMN IF NOT EXISTS fee_known BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE wallet_trades
    ADD COLUMN IF NOT EXISTS raw_data JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE wallet_scores
    ADD COLUMN IF NOT EXISTS evidence_status TEXT;
ALTER TABLE wallet_scores
    ADD COLUMN IF NOT EXISTS observed_weight NUMERIC(5,4);
ALTER TABLE wallet_scores
    ADD COLUMN IF NOT EXISTS warnings JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS wallet_discovery_sources (
    wallet_source_id BIGSERIAL PRIMARY KEY,
    wallet_id UUID NOT NULL REFERENCES wallets(wallet_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(wallet_id, source, source_ref)
);
CREATE INDEX IF NOT EXISTS idx_wallet_discovery_sources_source
    ON wallet_discovery_sources(source, last_seen DESC);

CREATE TABLE IF NOT EXISTS ingestion_checkpoints (
    checkpoint_name TEXT PRIMARY KEY,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS wallet_ingestion_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_wallet_trades_fee_known ON wallet_trades(fee_known);
INSERT INTO schema_migrations(version) VALUES('002_wallet_intelligence') ON CONFLICT DO NOTHING;
