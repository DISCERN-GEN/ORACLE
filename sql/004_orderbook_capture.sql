-- Prospective public CLOB order-book capture. Raw messages are retained so parser
-- improvements can replay evidence without pretending missing intervals existed.
CREATE TABLE IF NOT EXISTS clob_market_messages (
    message_id BIGSERIAL PRIMARY KEY,
    connection_id TEXT NOT NULL,
    subscription_version TEXT NOT NULL,
    asset_id TEXT,
    condition_id TEXT,
    event_type TEXT NOT NULL,
    venue_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    received_monotonic_ns BIGINT,
    book_hash TEXT,
    parser_version TEXT NOT NULL,
    raw_payload JSONB NOT NULL,
    parse_valid BOOLEAN NOT NULL DEFAULT FALSE,
    invalidation_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_clob_messages_asset_time
    ON clob_market_messages(asset_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_clob_messages_condition_time
    ON clob_market_messages(condition_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_clob_messages_type_time
    ON clob_market_messages(event_type, received_at DESC);

CREATE TABLE IF NOT EXISTS clob_book_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    asset_id TEXT NOT NULL,
    condition_id TEXT,
    venue_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL,
    received_monotonic_ns BIGINT,
    book_hash TEXT,
    bids JSONB NOT NULL,
    asks JSONB NOT NULL,
    source_message_id BIGINT REFERENCES clob_market_messages(message_id),
    parser_version TEXT NOT NULL,
    state_valid BOOLEAN NOT NULL DEFAULT TRUE,
    invalidation_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_clob_snapshot_asset_venue
    ON clob_book_snapshots(asset_id, venue_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_clob_snapshot_asset_received
    ON clob_book_snapshots(asset_id, received_at DESC);

CREATE TABLE IF NOT EXISTS clob_capture_gaps (
    gap_id BIGSERIAL PRIMARY KEY,
    connection_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    reason TEXT NOT NULL,
    affected_asset_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    recovered_at TIMESTAMPTZ
);

INSERT INTO schema_migrations(version) VALUES('004_orderbook_capture') ON CONFLICT DO NOTHING;

-- Capture reliability metadata added after v0.6 review.
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS invalidation_reason TEXT;
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS payload_sha256 TEXT;
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS parser_error TEXT;
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS raw_frame_type TEXT NOT NULL DEFAULT 'json';
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS received_monotonic_ns BIGINT;
ALTER TABLE clob_capture_gaps
    ADD COLUMN IF NOT EXISTS connection_attempt INTEGER NOT NULL DEFAULT 1;
ALTER TABLE clob_book_snapshots
    ADD COLUMN IF NOT EXISTS received_monotonic_ns BIGINT;
