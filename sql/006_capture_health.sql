-- 006: durable open gaps, explicit connection-health state, single-copy raw frames.
-- Idempotent.
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS parent_message_id BIGINT REFERENCES clob_market_messages(message_id);
ALTER TABLE clob_market_messages
    ADD COLUMN IF NOT EXISTS item_index INTEGER;
CREATE INDEX IF NOT EXISTS idx_clob_messages_parent
    ON clob_market_messages(parent_message_id) WHERE parent_message_id IS NOT NULL;

-- At most one open (unresolved) gap row per connection lineage is expected; open gaps
-- have ended_at NULL and survive a crash because they are written BEFORE the risky period.
CREATE INDEX IF NOT EXISTS idx_clob_gaps_open
    ON clob_capture_gaps(started_at) WHERE ended_at IS NULL;

CREATE TABLE IF NOT EXISTS clob_connection_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('interrupted', 'recovering', 'healthy')),
    since TIMESTAMPTZ NOT NULL,
    open_gap_id BIGINT REFERENCES clob_capture_gaps(gap_id),
    detail TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A reconnect is only 'recovering'. 'healthy' is reached solely by clob_mark_asset_valid
-- seeing no remaining invalid asset; reconnecting never validates history by itself.
CREATE OR REPLACE FUNCTION clob_set_connection_state(
    p_state TEXT, p_at TIMESTAMPTZ, p_gap_id BIGINT DEFAULT NULL, p_detail TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    IF p_state = 'healthy' THEN
        RAISE EXCEPTION 'healthy is derived, not set directly';
    END IF;
    INSERT INTO clob_connection_state(id, state, since, open_gap_id, detail)
    VALUES (1, p_state, p_at, p_gap_id, p_detail)
    ON CONFLICT (id) DO UPDATE
       SET since = CASE WHEN clob_connection_state.state = EXCLUDED.state
                        THEN clob_connection_state.since ELSE EXCLUDED.since END,
           state = EXCLUDED.state,
           open_gap_id = COALESCE(EXCLUDED.open_gap_id, clob_connection_state.open_gap_id),
           detail = EXCLUDED.detail, updated_at = now();
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION clob_refresh_connection_health(p_at TIMESTAMPTZ) RETURNS TEXT AS $$
DECLARE
    cur TEXT;
BEGIN
    SELECT state INTO cur FROM clob_connection_state WHERE id = 1 FOR UPDATE;
    IF cur = 'recovering'
       AND NOT EXISTS (SELECT 1 FROM clob_asset_validity WHERE state = 'invalid') THEN
        UPDATE clob_connection_state
           SET state='healthy', since=p_at, open_gap_id=NULL, updated_at=now() WHERE id = 1;
        RETURN 'healthy';
    END IF;
    RETURN cur;
END;
$$ LANGUAGE plpgsql;

INSERT INTO schema_migrations(version) VALUES('006_capture_health') ON CONFLICT DO NOTHING;
