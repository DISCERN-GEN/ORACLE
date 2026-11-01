-- Runs in CI after migrations. Raises on any wrong behaviour; leaves no rows behind.
BEGIN;
DO $$
DECLARE g BIGINT;
BEGIN
    PERFORM clob_mark_asset_valid('T-A', '2026-01-01 00:00:10+00');
    INSERT INTO clob_capture_gaps(connection_id,started_at,reason,affected_asset_ids,gap_kind)
        VALUES('t','2026-01-01 00:00:50+00','drop','["T-A"]','connection_loss') RETURNING gap_id INTO g;
    PERFORM clob_set_connection_state('interrupted','2026-01-01 00:00:50+00',g,'drop');
    PERFORM clob_mark_assets_invalid(ARRAY['T-A'],'2026-01-01 00:00:50+00','connection_loss',g);
    UPDATE clob_capture_gaps SET ended_at='2026-01-01 00:01:30+00' WHERE gap_id=g;
    PERFORM clob_set_connection_state('recovering','2026-01-01 00:01:30+00');
    IF NOT clob_asset_valid_at('T-A','2026-01-01 00:00:49+00') THEN RAISE 'valid before gap'; END IF;
    IF clob_asset_valid_at('T-A','2026-01-01 00:01:10+00') THEN RAISE 'gap interval must be invalid'; END IF;
    IF clob_asset_valid_at('T-A','2026-01-01 00:01:35+00') THEN RAISE 'reconnect alone must not validate'; END IF;
    IF clob_refresh_connection_health(now()) <> 'recovering' THEN RAISE 'healthy too early'; END IF;
    PERFORM clob_mark_asset_valid('T-A','2026-01-01 00:01:40+00');
    IF NOT clob_asset_valid_at('T-A','2026-01-01 00:01:40+00') THEN RAISE 'fresh book must validate'; END IF;
    IF clob_asset_valid_at('T-A','2026-01-01 00:01:39+00') THEN RAISE 'validity must not be backdated'; END IF;
END $$;
ROLLBACK;
