from datetime import UTC, datetime, timedelta

import pytest

from oracle_platform.book_capture import (
    decode_market_frame,
    is_copy_scorable,
    normalize_market_message,
)


def test_normalizes_full_book_and_preserves_raw_payload():
    now = datetime(2026, 11, 1, tzinfo=UTC)
    raw = {"event_type": "book", "asset_id": "token-1", "market": "condition-1",
           "timestamp": str(int(now.timestamp() * 1000)), "hash": "abc",
           "bids": [{"price": "0.4", "size": "12"}],
           "asks": [{"price": "0.5", "size": "9"}]}
    result = normalize_market_message(raw, now, "conn-a")
    assert result["asset_id"] == "token-1"
    assert result["bids"] == [{"price": "0.4", "size": "12"}]
    assert result["raw_payload"] == raw
    assert len(result["payload_sha256"]) == 64


def test_unknown_event_is_preserved_as_unparsed_not_fatal():
    result = normalize_market_message({"event_type": "future_event", "asset_id": "x"})
    assert result["parse_valid"] is False
    assert result["event_type"] == "future_event"
    assert "unsupported" in result["invalidation_reason"]


def test_rejects_bad_levels_for_caller_to_record_as_parse_error():
    with pytest.raises(ValueError):
        normalize_market_message({"event_type": "book", "asset_id": "x", "bids": [{"price": "-1", "size": "2"}]})


def test_copy_scorability_requires_exact_token_and_fresh_book():
    now = datetime.now(UTC)
    book = {"asset_id": "token-1", "condition_id": "mkt-1", "venue_timestamp": now,
            "bids": [{"price": "0.4", "size": "5"}], "asks": [{"price": "0.5", "size": "5"}],
            "state_valid": True}
    trade = {"token_id": "token-1", "market_id": "mkt-1", "executed_at": now + timedelta(milliseconds=500)}
    assert is_copy_scorable(book, trade) == (True, None)
    trade["token_id"] = "token-2"
    assert is_copy_scorable(book, trade)[1] == "token_mismatch"
    trade["token_id"] = "token-1"
    trade["executed_at"] = now + timedelta(seconds=2)
    assert is_copy_scorable(book, trade)[1] == "book_outside_time_tolerance"
    trade["executed_at"] = now - timedelta(milliseconds=1)
    assert is_copy_scorable(book, trade)[1] == "book_after_trade"


def test_raw_frame_decoder_handles_keepalives_malformed_and_json():
    assert decode_market_frame("PONG") == (None, None) or decode_market_frame("PONG")[1] is not None
    decoded, error = decode_market_frame("{bad json")
    assert decoded is None and error.startswith("json_decode_error:")
    decoded, error = decode_market_frame('{"event_type":"future_event"}')
    assert error is None and decoded["event_type"] == "future_event"
    decoded, error = decode_market_frame(b'{"event_type":"book"}')
    assert error is None and decoded["event_type"] == "book"
