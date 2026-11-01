-- 005: per-asset capture validity. An asset's order-book state is invalid from the
-- start of any capture gap (last persisted frame) until a fresh full `book`
-- snapshot arrives. Transitions are logged append-only so validity can be answered
-- for any past instant. Idempotent: safe to apply repeatedly.
ALTER TABLE clob_capture_gaps
    ADD COLUMN IF NOT EXISTS gap_kind TEXT NOT NULL DEFAULT 'connection_loss';
ALTER TABLE clob_capture_gaps
    ADD COLUMN IF NOT EXISTS last_frame_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_clob_messages_received
    ON clob_market_messages(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_clob_gaps_started
    ON clob_capture_gaps(started_at DESC);

CREATE TABLE IF NOT EXISTS clob_asset_validity (
    asset_id TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('valid', 'invalid')),
    invalid_since TIMESTAMPTZ,
    invalid_reason TEXT,
    gap_id BIGINT REFERENCES clob_capture_gaps(gap_id),
    valid_since TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clob_asset_validity_log (
    log_id BIGSERIAL PRIMARY KEY,
    asset_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('valid', 'invalid')),
    effective_at TIMESTAMPTZ NOT NULL,
    reason TEXT,
    gap_id BIGINT REFERENCES clob_capture_gaps(gap_id),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_clob_validity_log_asset_time
    ON clob_asset_validity_log(asset_id, effective_at DESC, log_id DESC);

-- Append-only: validity history may not be edited or deleted.
CREATE OR REPLACE FUNCTION clob_validity_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'clob_asset_validity_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_clob_validity_log_immutable ON clob_asset_validity_log;
CREATE TRIGGER trg_clob_validity_log_immutable
    BEFORE UPDATE OR DELETE ON clob_asset_validity_log
    FOR EACH ROW EXECUTE FUNCTION clob_validity_log_immutable();

-- Mark assets invalid from `since`. Already-invalid assets keep their earlier
-- invalid_since and original reason; only a real transition is logged.
CREATE OR REPLACE FUNCTION clob_mark_assets_invalid(
    p_assets TEXT[], p_since TIMESTAMPTZ, p_reason TEXT, p_gap_id BIGINT DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    a TEXT;
    prior TEXT;
    changed INTEGER := 0;
BEGIN
    FOREACH a IN ARRAY p_assets LOOP
        SELECT state INTO prior FROM clob_asset_validity WHERE asset_id = a FOR UPDATE;
        IF prior IS NULL THEN
            INSERT INTO clob_asset_validity(asset_id, state, invalid_since, invalid_reason, gap_id)
            VALUES (a, 'invalid', p_since, p_reason, p_gap_id);
        ELSIF prior = 'valid' THEN
            UPDATE clob_asset_validity
               SET state='invalid', invalid_since=p_since, invalid_reason=p_reason,
                   gap_id=p_gap_id, updated_at=now()
             WHERE asset_id = a;
        ELSE
            UPDATE clob_asset_validity
               SET gap_id = COALESCE(gap_id, p_gap_id), updated_at = now()
             WHERE asset_id = a;
            CONTINUE;
        END IF;
        INSERT INTO clob_asset_validity_log(asset_id, state, effective_at, reason, gap_id)
        VALUES (a, 'invalid', p_since, p_reason, p_gap_id);
        changed := changed + 1;
    END LOOP;
    RETURN changed;
END;
$$ LANGUAGE plpgsql;

-- A fresh full book snapshot makes an invalid (or never-seen) asset valid again.
CREATE OR REPLACE FUNCTION clob_mark_asset_valid(p_asset TEXT, p_at TIMESTAMPTZ)
RETURNS BOOLEAN AS $$
DECLARE
    prior TEXT;
BEGIN
    SELECT state INTO prior FROM clob_asset_validity WHERE asset_id = p_asset FOR UPDATE;
    IF prior = 'valid' THEN
        RETURN FALSE;
    END IF;
    IF prior IS NULL THEN
        INSERT INTO clob_asset_validity(asset_id, state, valid_since) VALUES (p_asset, 'valid', p_at);
    ELSE
        UPDATE clob_asset_validity
           SET state='valid', valid_since=p_at, invalid_since=NULL, invalid_reason=NULL,
               gap_id=NULL, updated_at=now()
         WHERE asset_id = p_asset;
    END IF;
    INSERT INTO clob_asset_validity_log(asset_id, state, effective_at, reason)
    VALUES (p_asset, 'valid', p_at, 'fresh_full_book_snapshot');
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Validity at an instant: the latest transition at or before it. No transition
-- on record means the state is unknown and is reported as not valid.
CREATE OR REPLACE FUNCTION clob_asset_valid_at(p_asset TEXT, p_at TIMESTAMPTZ)
RETURNS BOOLEAN AS $$
    SELECT COALESCE(
        (SELECT state = 'valid' FROM clob_asset_validity_log
          WHERE asset_id = p_asset AND effective_at <= p_at
          ORDER BY effective_at DESC, log_id DESC LIMIT 1),
        FALSE);
$$ LANGUAGE sql STABLE;

INSERT INTO schema_migrations(version) VALUES('005_capture_validity') ON CONFLICT DO NOTHING;
