from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

PARSER_VERSION = "oracle-clob-capture-v1"
BOOK_MAX_AGE_MS_PRIMARY = 1_000


def decode_market_frame(raw: str | bytes) -> tuple[Any | None, str | None]:
    """Decode a socket frame without treating keepalives or malformed data as fatal."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw), None
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"json_decode_error:{type(exc).__name__}:{exc}"


def _levels(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise ValueError("order book side must be a list")
    result: list[dict[str, str]] = []
    for level in raw:
        if not isinstance(level, dict) or "price" not in level or "size" not in level:
            raise ValueError("malformed order book level")
        price, size = Decimal(str(level["price"])), Decimal(str(level["size"]))
        if not price.is_finite() or not size.is_finite() or price < 0 or size < 0:
            raise ValueError("non-finite or negative order book level")
        result.append({"price": format(price, "f"), "size": format(size, "f")})
    return result


def normalize_market_message(message: dict[str, Any], received_at: datetime | None = None,
                             connection_id: str = "unknown") -> dict[str, Any]:
    """Validate and normalize a public CLOB market-channel message without inventing state."""
    received = received_at or datetime.now(UTC)
    if received.tzinfo is None:
        raise ValueError("received_at must be timezone-aware")
    event_type = str(message.get("event_type") or "").strip()
    allowed = {"book", "price_change", "tick_size_change", "last_trade_price",
               "best_bid_ask", "new_market", "market_resolved"}
    if event_type not in allowed:
        canonical = json.dumps(message, sort_keys=True, separators=(",", ":"), default=str)
        return {
            "connection_id": connection_id, "subscription_version": "assets_ids-market-v1",
            "asset_id": str(message.get("asset_id")) if message.get("asset_id") is not None else None,
            "condition_id": str(message.get("market")) if message.get("market") else None,
            "event_type": event_type or "unknown", "venue_timestamp": None,
            "received_at": received.astimezone(UTC), "book_hash": None,
            "bids": None, "asks": None, "raw_payload": message, "parse_valid": False,
            "invalidation_reason": f"unsupported market event type: {event_type or 'missing'}",
            "parser_version": PARSER_VERSION,
            "payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    asset_id = message.get("asset_id")
    if event_type == "book" and not asset_id:
        raise ValueError("book snapshot missing asset_id")
    venue_ms = message.get("timestamp")
    venue_time = None
    if venue_ms is not None:
        try:
            venue_time = datetime.fromtimestamp(int(venue_ms) / 1000, tz=UTC)
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            raise ValueError("invalid venue millisecond timestamp") from exc
    bids = _levels(message.get("bids", [])) if event_type == "book" else None
    asks = _levels(message.get("asks", [])) if event_type == "book" else None
    canonical = json.dumps(message, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "connection_id": connection_id,
        "subscription_version": "assets_ids-market-v1",
        "asset_id": str(asset_id) if asset_id is not None else None,
        "condition_id": str(message.get("market")) if message.get("market") else None,
        "event_type": event_type,
        "venue_timestamp": venue_time,
        "received_at": received.astimezone(UTC),
        "book_hash": str(message.get("hash")) if message.get("hash") else None,
        "bids": bids,
        "asks": asks,
        "raw_payload": message,
        "parse_valid": True,
        "invalidation_reason": None,
        "parser_version": PARSER_VERSION,
        "payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def is_copy_scorable(book: dict[str, Any], trade: dict[str, Any], max_age_ms: int = BOOK_MAX_AGE_MS_PRIMARY) -> tuple[bool, str | None]:
    """Apply protocol's conservative exact-token, validity and time-distance gate."""
    if not book.get("state_valid", True):
        return False, "book_state_invalid"
    if not book.get("asset_id") or str(book.get("asset_id")) != str(trade.get("token_id")):
        return False, "token_mismatch"
    if book.get("condition_id") and trade.get("market_id") and str(book["condition_id"]) != str(trade["market_id"]):
        return False, "market_mismatch"
    book_time, trade_time = book.get("venue_timestamp"), trade.get("executed_at")
    if not isinstance(book_time, datetime) or not isinstance(trade_time, datetime):
        return False, "timestamp_missing"
    if book_time.tzinfo is None or trade_time.tzinfo is None:
        return False, "timestamp_timezone_missing"
    # Only a book state observed at or before the wallet trade can describe
    # the market then. A future book is never accepted as a match.
    age_ms = (trade_time - book_time).total_seconds() * 1000
    if age_ms < 0:
        return False, "book_after_trade"
    if age_ms > max_age_ms:
        return False, "book_outside_time_tolerance"
    if not book.get("bids") or not book.get("asks"):
        return False, "incomplete_book_sides"
    return True, None
