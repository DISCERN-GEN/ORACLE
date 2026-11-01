from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

EVM_ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")


class DiscoveryClient(Protocol):
    async def leaderboard(self, limit: int = 100, time_period: str = "all", cursor: str | None = None) -> dict[str, Any]: ...
    async def markets(self, limit: int = 100, offset: int = 0, active: bool = True) -> list[dict[str, Any]]: ...
    async def market_trades(self, conditions: list[str], limit: int = 1000, cursor: str | None = None) -> dict[str, Any]: ...


class DiscoveryStore(Protocol):
    async def get_checkpoint(self, name: str) -> dict[str, Any] | None: ...
    async def set_checkpoint(self, name: str, state: dict[str, Any]) -> None: ...
    async def upsert_wallet(self, address: str, source: str = "polymarket_leaderboard", source_ref: str | None = None) -> bool: ...
    async def wallet_count(self) -> int: ...


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    requested_target: int
    unique_wallets_before: int
    unique_wallets_after: int
    added_this_run: int
    leaderboard_wallets_added: int
    market_trade_wallets_added: int
    leaderboard_pages: int
    market_pages: int
    market_trade_pages: int
    active_markets_seen: int
    conditions_queried: int
    leaderboard_complete: bool
    market_scan_complete: bool
    target_reached: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_target": self.requested_target,
            "unique_wallets_before": self.unique_wallets_before,
            "unique_wallets_after": self.unique_wallets_after,
            "added_this_run": self.added_this_run,
            "leaderboard_wallets_added": self.leaderboard_wallets_added,
            "market_trade_wallets_added": self.market_trade_wallets_added,
            "leaderboard_pages": self.leaderboard_pages,
            "market_pages": self.market_pages,
            "market_trade_pages": self.market_trade_pages,
            "active_markets_seen": self.active_markets_seen,
            "conditions_queried": self.conditions_queried,
            "leaderboard_complete": self.leaderboard_complete,
            "market_scan_complete": self.market_scan_complete,
            "target_reached": self.target_reached,
            "errors": list(self.errors),
            "sources": ["polymarket_public_leaderboard", "polymarket_active_market_trade_feed"],
        }


def _wallet_address(row: dict[str, Any]) -> str | None:
    raw = (row.get("proxy_wallet") or row.get("proxyWallet") or row.get("proxy_wallet_address")
           or row.get("proxyWalletAddress") or row.get("address") or "")
    address = str(raw).lower()
    return address if EVM_ADDRESS.fullmatch(address) else None


def _next_cursor(page: dict[str, Any]) -> str | None:
    pagination = page.get("pagination") or {}
    cursor = pagination.get("next_cursor")
    return str(cursor) if cursor not in (None, "") else None


def _condition_id(market: dict[str, Any]) -> str | None:
    value = str(market.get("conditionId") or market.get("condition_id") or "")
    return value if re.fullmatch(r"0x[a-fA-F0-9]{64}", value) else None


async def discover_wallets(
    client: DiscoveryClient,
    store: DiscoveryStore,
    *,
    target: int = 5_000,
    leaderboard_page_size: int = 500,
    market_page_size: int = 500,
    trade_page_size: int = 1_000,
    max_leaderboard_pages: int = 100,
    max_market_pages: int = 100,
    max_trade_pages_per_batch: int = 100,
) -> DiscoveryReport:
    """Resume-safe discovery from leaderboard and active-market trade feeds.

    Checkpoints preserve opaque cursors and pending market-condition batches. The
    target may be exceeded by the final processed API page; no candidate is dropped
    merely to force an exact count.
    """
    if not 1 <= target <= 10_000:
        raise ValueError("target must be between 1 and 10,000")
    if not 1 <= leaderboard_page_size <= 500 or not 1 <= market_page_size <= 500:
        raise ValueError("Leaderboard/market page size must be between 1 and 500")
    if not 1 <= trade_page_size <= 1_000:
        raise ValueError("Trade page size must be between 1 and 1,000")

    before = await store.wallet_count()
    leaderboard_added = market_added = lb_pages = market_pages = trade_pages = 0
    markets_seen = conditions_queried = 0
    errors: list[str] = []

    # Source 1: ranked leaderboard, resumed with the opaque Data API cursor.
    lb_state = await store.get_checkpoint("wallet_discovery:leaderboard") or {}
    lb_cursor = lb_state.get("next_cursor")
    lb_complete = bool(lb_state.get("complete", False))
    for _ in range(max_leaderboard_pages if not lb_complete else 0):
        if await store.wallet_count() >= target:
            break
        try:
            page = await client.leaderboard(limit=leaderboard_page_size, time_period="all", cursor=lb_cursor)
            rows = page.get("data") or []
            if not isinstance(rows, list):
                raise ValueError("Leaderboard data was not a list")
            for row in rows:
                if isinstance(row, dict):
                    address = _wallet_address(row)
                    if address and await store.upsert_wallet(
                        address, "polymarket_leaderboard", str(row.get("rank") or "")
                    ):
                        leaderboard_added += 1
            lb_pages += 1
            lb_cursor = _next_cursor(page)
            lb_complete = lb_cursor is None
            await store.set_checkpoint("wallet_discovery:leaderboard", {
                "next_cursor": lb_cursor, "complete": lb_complete,
                "pages_read_total": int(lb_state.get("pages_read_total", 0)) + lb_pages,
                "last_page_rows": len(rows), "updated_at": datetime.now(UTC).isoformat(),
            })
            if lb_complete:
                break
        except Exception as exc:
            errors.append(f"leaderboard: {type(exc).__name__}: {str(exc)[:180]}")
            break

    # Source 2: active markets -> batches of at most 20 condition IDs -> trade feed.
    state = await store.get_checkpoint("wallet_discovery:active_markets") or {}
    market_offset = int(state.get("next_offset", 0))
    pending_conditions = list(state.get("pending_conditions") or [])
    batch_cursor = state.get("batch_cursor")
    page_advance = int(state.get("page_advance", 0))
    page_is_last = bool(state.get("page_is_last", False))
    market_complete = bool(state.get("complete", False))
    historical_markets_seen = int(state.get("active_markets_seen", 0))

    async def persist_market_state(*, complete: bool | None = None) -> None:
        await store.set_checkpoint("wallet_discovery:active_markets", {
            "next_offset": market_offset,
            "pending_conditions": pending_conditions,
            "batch_cursor": batch_cursor,
            "page_advance": page_advance,
            "page_is_last": page_is_last,
            "complete": market_complete if complete is None else complete,
            "active_markets_seen": historical_markets_seen + markets_seen,
            "updated_at": datetime.now(UTC).isoformat(),
        })

    market_pages_budget = max_market_pages
    while market_pages_budget > 0 and not market_complete:
        if await store.wallet_count() >= target and trade_pages > 0:
            break

        if not pending_conditions:
            try:
                page_markets = await client.markets(limit=market_page_size, offset=market_offset, active=True)
                market_pages += 1
                market_pages_budget -= 1
                if not isinstance(page_markets, list):
                    raise ValueError("Gamma active markets response was not a list")
                markets_seen += len(page_markets)
                pending_conditions = list(dict.fromkeys(
                    condition for item in page_markets if isinstance(item, dict)
                    and item.get("closed") is not True
                    and item.get("active") is not False
                    for condition in [_condition_id(item)] if condition
                ))
                page_advance = len(page_markets)
                page_is_last = len(page_markets) < market_page_size
                batch_cursor = None
                await persist_market_state()
                if not page_markets:
                    market_complete = True
                    await persist_market_state(complete=True)
                    break
            except Exception as exc:
                errors.append(f"active_markets: {type(exc).__name__}: {str(exc)[:180]}")
                break

        if pending_conditions:
            batch = pending_conditions[:20]
            conditions_queried += len(batch)
            batch_done = False
            cursor = batch_cursor
            try:
                for _ in range(max_trade_pages_per_batch):
                    if await store.wallet_count() >= target and trade_pages > 0:
                        break
                    page = await client.market_trades(batch, limit=trade_page_size, cursor=cursor)
                    rows = page.get("data") or []
                    if not isinstance(rows, list):
                        raise ValueError("Market trade data was not a list")
                    for row in rows:
                        if isinstance(row, dict):
                            address = _wallet_address(row)
                            if address and await store.upsert_wallet(
                                address, "polymarket_active_market_trade",
                                str(row.get("condition_id") or row.get("conditionId") or ""),
                            ):
                                market_added += 1
                    trade_pages += 1
                    cursor = _next_cursor(page)
                    if cursor is None:
                        batch_done = True
                        break
                if not batch_done:
                    batch_cursor = cursor
                    await persist_market_state()
                    break
                # Advance the batch only after the terminal page was successfully read.
                pending_conditions = pending_conditions[len(batch):]
                batch_cursor = None
                await persist_market_state()
            except Exception as exc:
                batch_cursor = cursor
                await persist_market_state()
                errors.append(f"active_market_trades: {type(exc).__name__}: {str(exc)[:180]}")
                break

        if not pending_conditions and page_advance:
            market_offset += page_advance
            page_advance = 0
            if page_is_last:
                market_complete = True
            page_is_last = False
            await persist_market_state()

    after = await store.wallet_count()
    return DiscoveryReport(
        target, before, after, max(0, after-before), leaderboard_added, market_added,
        lb_pages, market_pages, trade_pages, markets_seen, conditions_queried,
        lb_complete, market_complete, after >= target, tuple(errors),
    )

def normalize_public_trade(row: dict[str, Any], fallback_wallet: str | None = None) -> dict[str, Any] | None:
    """Normalize a v2 trade row; fees remain explicitly unknown unless supplied."""
    wallet_raw = (row.get("proxy_wallet") or row.get("proxyWallet") or fallback_wallet or "")
    wallet = str(wallet_raw).lower()
    if not EVM_ADDRESS.fullmatch(wallet):
        return None
    market_id = str(row.get("condition_id") or row.get("conditionId") or row.get("market_id") or row.get("market") or "")
    token_id = str(row.get("token_id") or row.get("asset") or row.get("tokenId") or "")
    side = str(row.get("side") or "").upper()
    if not market_id or not token_id or side not in {"BUY", "SELL"}:
        return None
    try:
        price = Decimal(str(row.get("price")))
        quantity = Decimal(str(row.get("size")))
        timestamp = int(row.get("timestamp"))
        if not Decimal("0") <= price <= Decimal("1") or quantity <= 0 or timestamp <= 0:
            return None
        executed_at = datetime.fromtimestamp(timestamp, tz=UTC)
    except (InvalidOperation, TypeError, ValueError, OSError, OverflowError):
        return None
    fee_raw = row.get("fee")
    try:
        fee = Decimal(str(fee_raw)) if fee_raw is not None else Decimal("0")
        fee_known = fee_raw is not None and fee >= 0
        if fee < 0:
            fee = Decimal("0")
    except InvalidOperation:
        fee, fee_known = Decimal("0"), False
    identity = {
        "wallet": wallet, "market_id": market_id, "token_id": token_id, "side": side,
        "price": str(price), "quantity": str(quantity), "timestamp": timestamp,
        "transaction_hash": row.get("transaction_hash") or row.get("transactionHash"),
        "source_id": row.get("id") or row.get("trade_id"),
    }
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    # The v2 trade feed's documented row schema does not promise a unique trade ID;
    # retain the fingerprint method in raw_data so repeated/identical fills can be audited.
    return {
        "trade_id": "pmv2:" + fingerprint,
        "wallet_address": wallet,
        "market_id": market_id,
        "token_id": token_id,
        "side": side,
        "price": price,
        "quantity": quantity,
        "fee": fee,
        "fee_known": fee_known,
        "executed_at": executed_at,
        "source_ref": identity["transaction_hash"],
        "raw_data": {**row, "_oracle_trade_id_method": "sha256_normalized_row_v1", "_oracle_fee_known": fee_known},
    }


async def ingest_wallet_trade_history(
    client: Any,
    store: Any,
    *,
    max_wallets: int = 25,
    max_pages_per_wallet: int = 20,
    page_size: int = 1_000,
) -> dict[str, Any]:
    """Ingest paginated, user-scoped trade histories with per-wallet checkpoints."""
    if not 1 <= max_wallets <= 1000 or not 1 <= max_pages_per_wallet <= 100:
        raise ValueError("Invalid wallet/page budget")
    if not 1 <= page_size <= 1000:
        raise ValueError("Trade page size must be between 1 and 1,000")
    addresses = await store.list_wallets_for_trade_ingestion(max_wallets)
    wallets_started = pages_read = trades_inserted = invalid_rows = completed = partial = 0
    errors: list[str] = []
    for address in addresses:
        wallets_started += 1
        per_wallet_trades_inserted = 0
        checkpoint_name = f"wallet_trade_ingestion:{address}"
        state = await store.get_checkpoint(checkpoint_name) or {}
        cursor = state.get("next_cursor")
        wallet_pages = 0
        done = False
        try:
            while wallet_pages < max_pages_per_wallet:
                page = await client.wallet_trades(address, limit=page_size, cursor=cursor)
                rows = page.get("data") or []
                if not isinstance(rows, list):
                    raise ValueError("Wallet trade data was not a list")
                for row in rows:
                    if not isinstance(row, dict):
                        invalid_rows += 1
                        continue
                    normalized = normalize_public_trade(row, fallback_wallet=address)
                    if normalized is None:
                        invalid_rows += 1
                        continue
                    if await store.save_wallet_trade(normalized):
                        trades_inserted += 1
                        per_wallet_trades_inserted += 1
                wallet_pages += 1
                pages_read += 1
                cursor = _next_cursor(page)
                done = cursor is None
                await store.set_checkpoint(checkpoint_name, {
                    "next_cursor": cursor, "complete": done,
                    "pages_read_total": int(state.get("pages_read_total", 0)) + wallet_pages,
                    "trades_inserted_total": int(state.get("trades_inserted_total", 0)) + per_wallet_trades_inserted,
                    "last_page_rows": len(rows),
                    "updated_at": datetime.now(UTC).isoformat(),
                    "history_window": "full_history_start_1",
                    "maker_rows_included": True,
                })
                if done:
                    completed += 1
                    break
            if not done:
                partial += 1
        except Exception as exc:
            partial += 1
            errors.append(f"{address}: {type(exc).__name__}: {str(exc)[:160]}")
            await store.set_checkpoint(checkpoint_name, {
                "next_cursor": cursor, "complete": False,
                "pages_read_total": int(state.get("pages_read_total", 0)) + wallet_pages,
                "last_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "updated_at": datetime.now(UTC).isoformat(),
            })
    remaining = await store.list_wallets_for_trade_ingestion(1)
    return {
        "wallets_started": wallets_started,
        "wallets_completed": completed,
        "wallets_partial_or_failed": partial,
        "pages_read": pages_read,
        "new_trades_inserted": trades_inserted,
        "invalid_or_unusable_rows": invalid_rows,
        "wallets_remaining_at_least": len(remaining),
        "errors": errors,
        "history_window": "full_history_start_1",
        "fee_note": "Public trade rows do not expose a per-fill fee in their documented schema; fee_known remains false unless a fee is explicitly present.",
    }


_ACTIVITY_FEEDS = {"activity", "activity_tips", "activity_combos"}

def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None

def normalize_public_activity(
    row: dict[str, Any],
    fallback_wallet: str | None = None,
    source_feed: str = "activity",
) -> dict[str, Any] | None:
    """Normalize activity without inventing cashflow signs, fees, or economics.

    The activity and combo feeds have distinct schemas. All original fields are
    retained; unknown actions and missing numeric values remain observable.
    """
    if source_feed not in _ACTIVITY_FEEDS:
        raise ValueError(f"Unsupported activity source feed: {source_feed}")
    wallet_raw = row.get("proxy_wallet") or row.get("proxyWallet") or fallback_wallet or ""
    wallet = str(wallet_raw).lower()
    if not EVM_ADDRESS.fullmatch(wallet):
        return None
    activity_type = str(row.get("type") or "").upper().strip()
    if not activity_type:
        return None
    timestamp_raw = row.get("timestamp")
    try:
        timestamp = int(timestamp_raw)
        if timestamp <= 0:
            return None
        occurred_at = datetime.fromtimestamp(timestamp, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None

    condition_id = str(
        row.get("condition_id") or row.get("conditionId")
        or row.get("combo_condition_id") or ""
    ) or None
    token_id = str(
        row.get("token_id") or row.get("tokenId") or row.get("asset")
        or row.get("combo_position_id") or ""
    ) or None
    side = str(row.get("side") or "").upper() or None
    if side not in {None, "BUY", "SELL"}:
        side = None
    price = _optional_decimal(row.get("price"))
    size = _optional_decimal(row.get("size"))
    usdc_size = _optional_decimal(row.get("usdc_size") if "usdc_size" in row else row.get("usdcSize"))
    amount_usdc = _optional_decimal(row.get("amount_usdc"))
    payout_usdc = _optional_decimal(row.get("payout_usdc"))
    tx_hash = row.get("transaction_hash") or row.get("transactionHash")
    source_event_id = row.get("id")

    # A combo event has a documented tx_hash-log_index ID. Standard activity
    # rows do not guarantee an event ID, so fall back to a stable row fingerprint.
    identity = {
        "wallet": wallet, "source_feed": source_feed, "source_event_id": source_event_id,
        "transaction_hash": tx_hash, "type": activity_type, "timestamp": timestamp,
        "condition_id": condition_id, "token_id": token_id, "side": side,
        "price": str(price) if price is not None else None,
        "size": str(size) if size is not None else None,
        "usdc_size": str(usdc_size) if usdc_size is not None else None,
        "amount_usdc": str(amount_usdc) if amount_usdc is not None else None,
        "payout_usdc": str(payout_usdc) if payout_usdc is not None else None,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    activity_id = (f"pmv2:{source_feed}:{source_event_id}"
                   if source_feed == "activity_combos" and source_event_id
                   else f"pmv2:{source_feed}:{digest}")
    return {
        "activity_id": activity_id, "wallet_address": wallet, "source_feed": source_feed,
        "activity_type": activity_type, "condition_id": condition_id, "token_id": token_id,
        "side": side, "price": price, "size": size, "usdc_size": usdc_size,
        "amount_usdc": amount_usdc, "payout_usdc": payout_usdc,
        "occurred_at": occurred_at, "transaction_hash": str(tx_hash) if tx_hash else None,
        "source_event_id": str(source_event_id) if source_event_id else None,
        "raw_data": {**row, "_oracle_source_feed": source_feed,
                     "_oracle_cashflow_sign_inferred": False, "_oracle_fee_known": False},
    }

async def ingest_wallet_activity_history(
    client: Any,
    store: Any,
    *,
    max_wallets: int = 25,
    max_pages_per_wallet: int = 20,
    page_size: int = 1_000,
    feeds: tuple[str, ...] = ("activity", "activity_tips", "activity_combos"),
) -> dict[str, Any]:
    """Ingest standard and combo account-activity feeds with independent cursors."""
    if not 1 <= max_wallets <= 1_000 or not 1 <= max_pages_per_wallet <= 100:
        raise ValueError("Invalid wallet/page budget")
    if not 1 <= page_size <= 1_000:
        raise ValueError("Activity page size must be between 1 and 1,000")
    if not feeds or any(feed not in _ACTIVITY_FEEDS for feed in feeds):
        raise ValueError("feeds must contain activity and/or activity_combos")

    total = {"wallet_feed_walks_started": 0, "wallet_feed_walks_completed": 0,
             "wallet_feed_walks_partial_or_failed": 0, "pages_read": 0,
             "new_events_inserted": 0, "invalid_or_unusable_rows": 0}
    by_feed: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    for feed in feeds:
        feed_stats = {"wallets_started": 0, "wallets_completed": 0,
                      "wallets_partial_or_failed": 0, "pages_read": 0,
                      "new_events_inserted": 0, "invalid_or_unusable_rows": 0}
        addresses = await store.list_wallets_for_activity_ingestion(feed, max_wallets)
        for address in addresses:
            feed_stats["wallets_started"] += 1
            total["wallet_feed_walks_started"] += 1
            checkpoint_name = f"wallet_activity:{feed}:{address}"
            state = await store.get_checkpoint(checkpoint_name) or {}
            cursor = state.get("next_cursor")
            wallet_pages = inserted = invalid = 0
            done = False
            try:
                while wallet_pages < max_pages_per_wallet:
                    if feed in {"activity", "activity_tips"}:
                        page = await client.wallet_activity(
                            address, limit=page_size, cursor=cursor,
                            activity_type="TIP" if feed == "activity_tips" else None,
                        )
                    else:
                        page = await client.wallet_combo_activity(address, limit=page_size, cursor=cursor)
                    rows = page.get("data") or []
                    if not isinstance(rows, list):
                        raise ValueError("Activity data was not a list")
                    for row in rows:
                        if not isinstance(row, dict):
                            invalid += 1
                            continue
                        normalized = normalize_public_activity(row, address, feed)
                        if normalized is None:
                            invalid += 1
                            continue
                        if await store.save_wallet_activity(normalized):
                            inserted += 1
                    wallet_pages += 1
                    feed_stats["pages_read"] += 1
                    total["pages_read"] += 1
                    cursor = _next_cursor(page)
                    done = cursor is None
                    await store.set_checkpoint(checkpoint_name, {
                        "next_cursor": cursor, "complete": done,
                        "pages_read_total": int(state.get("pages_read_total", 0)) + wallet_pages,
                        "events_inserted_total": int(state.get("events_inserted_total", 0)) + inserted,
                        "last_page_rows": len(rows), "updated_at": datetime.now(UTC).isoformat(),
                        "history_window": "full_history_start_1" if feed in {"activity", "activity_tips"} else "combo_feed_full_available_history",
                        "sort_direction": "DESC" if feed in {"activity", "activity_tips"} else None,
                        "deposits_withdrawals_included": feed in {"activity", "activity_tips"},
                        "activity_type_filter": "TIP" if feed == "activity_tips" else None,
                    })
                    if done:
                        feed_stats["wallets_completed"] += 1
                        total["wallet_feed_walks_completed"] += 1
                        break
                if not done:
                    feed_stats["wallets_partial_or_failed"] += 1
                    total["wallet_feed_walks_partial_or_failed"] += 1
                feed_stats["new_events_inserted"] += inserted
                feed_stats["invalid_or_unusable_rows"] += invalid
                total["new_events_inserted"] += inserted
                total["invalid_or_unusable_rows"] += invalid
            except Exception as exc:
                feed_stats["wallets_partial_or_failed"] += 1
                total["wallet_feed_walks_partial_or_failed"] += 1
                errors.append(f"{feed}:{address}: {type(exc).__name__}: {str(exc)[:160]}")
                await store.set_checkpoint(checkpoint_name, {
                    "next_cursor": cursor, "complete": False,
                    "pages_read_total": int(state.get("pages_read_total", 0)) + wallet_pages,
                    "last_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                    "updated_at": datetime.now(UTC).isoformat(),
                })
        by_feed[feed] = feed_stats
    return {
        **total, "by_feed": by_feed, "errors": errors,
        "history_window": "full available source history; activity start=1",
        "accounting_note": (
            "Activity rows are retained as source evidence. ORACLE does not infer cashflow signs, "
            "opening balance, realized P&L, or fees from activity type names or absent fields. "
            "Combo lifecycle activity is ingested separately. Trade rows may overlap the trade feed "
            "and are not added to reconstructed trade inventory by this job."
        ),
    }
