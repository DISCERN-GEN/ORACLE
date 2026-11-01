-- Durable standard and combo account-activity archive.
-- Raw rows are retained; this migration deliberately does not infer economic signs.

CREATE TABLE IF NOT EXISTS wallet_activity (
    wallet_activity_id BIGSERIAL PRIMARY KEY,
    activity_id TEXT NOT NULL,
    wallet_id UUID NOT NULL REFERENCES wallets(wallet_id) ON DELETE CASCADE,
    source_feed TEXT NOT NULL CHECK(source_feed IN ('activity','activity_tips','activity_combos')),
    activity_type TEXT NOT NULL,
    condition_id TEXT,
    token_id TEXT,
    side TEXT CHECK(side IS NULL OR side IN ('BUY','SELL')),
    price NUMERIC(30,16),
    size NUMERIC(30,16),
    usdc_size NUMERIC(30,16),
    amount_usdc NUMERIC(30,16),
    payout_usdc NUMERIC(30,16),
    occurred_at TIMESTAMPTZ NOT NULL,
    transaction_hash TEXT,
    source_event_id TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(wallet_id,source_feed,activity_id)
);

CREATE INDEX IF NOT EXISTS idx_wallet_activity_wallet_time
    ON wallet_activity(wallet_id,occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_activity_type_time
    ON wallet_activity(activity_type,occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_activity_tx_hash
    ON wallet_activity(transaction_hash) WHERE transaction_hash IS NOT NULL;

INSERT INTO schema_migrations(version) VALUES('003_wallet_activity') ON CONFLICT DO NOTHING;
