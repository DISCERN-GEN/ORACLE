from __future__ import annotations

import asyncio
from datetime import UTC

from oracle_platform.wallet_discovery import (
    discover_wallets,
    ingest_wallet_activity_history,
    ingest_wallet_trade_history,
    normalize_public_activity,
    normalize_public_trade,
)

W1 = "0x" + "1" * 40
W2 = "0x" + "2" * 40
W3 = "0x" + "3" * 40
C1 = "0x" + "a" * 64
C2 = "0x" + "b" * 64


class FakeStore:
    def __init__(self):
        self.wallets: set[str] = set()
        self.checkpoints: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self.activities: dict[tuple[str, str], dict] = {}

    async def wallet_count(self):
        return len(self.wallets)

    async def upsert_wallet(self, address, source="", source_ref=None):
        before = len(self.wallets)
        self.wallets.add(address)
        return len(self.wallets) > before

    async def get_checkpoint(self, name):
        return self.checkpoints.get(name)

    async def set_checkpoint(self, name, state):
        self.checkpoints[name] = dict(state)

    async def list_wallets_for_trade_ingestion(self, limit):
        done = {name.split(":", 1)[1] for name, state in self.checkpoints.items()
                if name.startswith("wallet_trade_ingestion:") and state.get("complete")}
        return sorted(self.wallets - done)[:limit]

    async def save_wallet_trade(self, trade):
        if trade["trade_id"] in self.trades:
            return False
        self.trades[trade["trade_id"]] = trade
        return True

    async def list_wallets_for_activity_ingestion(self, feed, limit):
        done = {name.rsplit(":", 1)[1] for name, state in self.checkpoints.items()
                if name.startswith(f"wallet_activity:{feed}:") and state.get("complete")}
        return sorted(self.wallets - done)[:limit]

    async def save_wallet_activity(self, activity):
        key = (activity["source_feed"], activity["activity_id"])
        if key in self.activities:
            return False
        self.activities[key] = activity
        return True


class FakeDiscoveryClient:
    def __init__(self):
        self.leaderboard_calls = 0
        self.market_calls = 0
        self.trade_calls = 0

    async def leaderboard(self, limit=100, time_period="all", cursor=None):
        self.leaderboard_calls += 1
        if cursor is None:
            return {"data": [{"proxyWallet": W1}, {"proxyWallet": W2}],
                    "pagination": {"next_cursor": "lb-next"}}
        return {"data": [{"proxy_wallet": W2}], "pagination": {"next_cursor": None}}

    async def markets(self, limit=100, offset=0, active=True):
        self.market_calls += 1
        if offset == 0:
            return [
                {"conditionId": C1, "active": True, "closed": False},
                {"conditionId": C2, "active": True, "closed": False},
            ]
        return []

    async def market_trades(self, conditions, limit=1000, cursor=None):
        self.trade_calls += 1
        assert len(conditions) <= 20
        return {"data": [{"proxy_wallet": W2}, {"proxy_wallet": W3}],
                "pagination": {"next_cursor": None}}


class FakeIngestionClient:
    def __init__(self):
        self.calls = 0

    async def wallet_trades(self, address, limit=1000, cursor=None):
        self.calls += 1
        if cursor is None:
            return {
                "data": [{"proxy_wallet": address, "condition_id": C1, "token_id": "token-a",
                          "side": "BUY", "price": 0.4, "size": 5, "timestamp": 1793500000,
                          "transaction_hash": "0xabc"}],
                "pagination": {"next_cursor": "next-page"},
            }
        return {
            "data": [{"proxy_wallet": address, "condition_id": C1, "token_id": "token-a",
                      "side": "SELL", "price": 0.6, "size": 2, "timestamp": 1793500100,
                      "transaction_hash": "0xdef"}],
            "pagination": {"next_cursor": None},
        }


def test_normalize_public_v2_trade_keeps_fee_unknown_and_fingerprint():
    row = {
        "proxy_wallet": W1, "condition_id": C1, "token_id": "token-1",
        "side": "BUY", "price": 0.45, "size": 10, "timestamp": 1793500000,
        "transaction_hash": "0xtx",
    }
    trade = normalize_public_trade(row)
    assert trade is not None
    assert trade["wallet_address"] == W1
    assert trade["fee_known"] is False
    assert trade["trade_id"].startswith("pmv2:")
    assert normalize_public_trade(row)["trade_id"] == trade["trade_id"]
    assert trade["executed_at"].tzinfo == UTC


def test_normalize_public_trade_rejects_incomplete_identity_and_bad_price():
    assert normalize_public_trade({"proxy_wallet": W1}) is None
    row = {
        "proxy_wallet": W1, "condition_id": C1, "token_id": "token-1",
        "side": "BUY", "price": 1.01, "size": 1, "timestamp": 1793500000,
    }
    assert normalize_public_trade(row) is None


def test_discovery_uses_leaderboard_and_active_market_trade_feed():
    store, client = FakeStore(), FakeDiscoveryClient()
    report = asyncio.run(discover_wallets(
        client, store, target=10, leaderboard_page_size=2, market_page_size=2,
        max_leaderboard_pages=5, max_market_pages=5,
    ))
    assert report.unique_wallets_after == 3
    assert report.leaderboard_pages == 2
    assert report.market_trade_pages == 1
    assert report.leaderboard_complete is True
    assert report.market_scan_complete is True
    assert store.checkpoints["wallet_discovery:leaderboard"]["complete"] is True
    assert store.checkpoints["wallet_discovery:active_markets"]["complete"] is True


def test_wallet_trade_ingestion_resumes_cursor_and_persists_both_pages():
    store = FakeStore()
    store.wallets.add(W1)
    client = FakeIngestionClient()
    result = asyncio.run(ingest_wallet_trade_history(
        client, store, max_wallets=1, max_pages_per_wallet=5, page_size=10,
    ))
    assert result["wallets_completed"] == 1
    assert result["pages_read"] == 2
    assert result["new_trades_inserted"] == 2
    assert client.calls == 2
    checkpoint = store.checkpoints[f"wallet_trade_ingestion:{W1}"]
    assert checkpoint["complete"] is True
    assert checkpoint["history_window"] == "full_history_start_1"


class PagedMarketClient(FakeDiscoveryClient):
    async def market_trades(self, conditions, limit=1000, cursor=None):
        self.trade_calls += 1
        if cursor is None:
            return {"data": [{"proxy_wallet": W3}],
                    "pagination": {"next_cursor": "market-cursor"}}
        return {"data": [{"proxy_wallet": W2}], "pagination": {"next_cursor": None}}


def test_market_discovery_persists_and_resumes_opaque_cursor():
    store, client = FakeStore(), PagedMarketClient()
    first = asyncio.run(discover_wallets(
        client, store, target=10, leaderboard_page_size=2, market_page_size=2,
        max_leaderboard_pages=1, max_market_pages=1, max_trade_pages_per_batch=1,
    ))
    cp = store.checkpoints["wallet_discovery:active_markets"]
    assert cp["batch_cursor"] == "market-cursor"
    assert cp["pending_conditions"] == [C1, C2]
    assert first.market_scan_complete is False

    second = asyncio.run(discover_wallets(
        client, store, target=10, leaderboard_page_size=2, market_page_size=2,
        max_leaderboard_pages=1, max_market_pages=1, max_trade_pages_per_batch=2,
    ))
    assert second.market_scan_complete is True
    assert store.wallets == {W1, W2, W3}


def test_wallet_trade_history_ingestion_resumes_per_wallet():
    store = FakeStore()
    store.wallets.add(W1)
    client = FakeIngestionClient()
    first = asyncio.run(ingest_wallet_trade_history(
        client, store, max_wallets=1, max_pages_per_wallet=1, page_size=10,
    ))
    assert first["wallets_partial_or_failed"] == 1
    cp = store.checkpoints[f"wallet_trade_ingestion:{W1}"]
    assert cp["next_cursor"] == "next-page"
    second = asyncio.run(ingest_wallet_trade_history(
        client, store, max_wallets=1, max_pages_per_wallet=1, page_size=10,
    ))
    assert second["wallets_completed"] == 1
    assert second["new_trades_inserted"] == 1
    assert len(store.trades) == 2


def test_normalize_activity_retains_amounts_without_inventing_cashflow_signs():
    row = {
        "proxy_wallet": W1, "type": "REDEEM", "timestamp": 1793501000,
        "condition_id": C1, "token_id": "token-yes", "size": 10,
        "usdc_size": 8.5, "transaction_hash": "0xredeem",
    }
    event = normalize_public_activity(row)
    assert event is not None
    assert event["activity_type"] == "REDEEM"
    assert event["size"] == 10
    assert event["usdc_size"] == 8.5
    assert event["raw_data"]["_oracle_cashflow_sign_inferred"] is False
    assert event["raw_data"]["_oracle_fee_known"] is False
    assert event["source_feed"] == "activity"


def test_normalize_combo_activity_supports_combo_ids_and_missing_amounts():
    row = {
        "proxy_wallet": W2, "type": "COMPRESS", "timestamp": 1793502000,
        "combo_condition_id": "0x03combo", "combo_position_id": "combo-token",
        "id": "0xtx-17", "amount_usdc": None,
    }
    event = normalize_public_activity(row, source_feed="activity_combos")
    assert event is not None
    assert event["activity_id"] == "pmv2:activity_combos:0xtx-17"
    assert event["condition_id"] == "0x03combo"
    assert event["token_id"] == "combo-token"
    assert event["amount_usdc"] is None


class FakeActivityClient:
    def __init__(self):
        self.calls = []

    async def wallet_activity(self, address, limit=1000, cursor=None, activity_type=None):
        feed = "activity_tips" if activity_type == "TIP" else "activity"
        self.calls.append((feed, address, cursor))
        if activity_type == "TIP":
            return {"data": [{"proxy_wallet": address, "type": "TIP",
                              "timestamp": 1793503500, "usdc_size": 2}],
                    "pagination": {"next_cursor": None}}
        if cursor is None:
            return {"data": [{"proxy_wallet": address, "type": "DEPOSIT",
                              "timestamp": 1793503000, "usdc_size": 100}],
                    "pagination": {"next_cursor": "activity-next"}}
        return {"data": [{"proxy_wallet": address, "type": "WITHDRAWAL",
                           "timestamp": 1793504000, "usdc_size": 25}],
                "pagination": {"next_cursor": None}}

    async def wallet_combo_activity(self, address, limit=1000, cursor=None):
        self.calls.append(("activity_combos", address, cursor))
        return {"data": [{"proxy_wallet": address, "type": "REDEEM",
                          "timestamp": 1793505000, "id": "0xcombo-1",
                          "payout_usdc": 12}],
                "pagination": {"next_cursor": None}}


def test_activity_ingestion_resumes_both_feeds_and_keeps_event_types_separate():
    store = FakeStore()
    store.wallets.add(W1)
    client = FakeActivityClient()
    first = asyncio.run(ingest_wallet_activity_history(
        client, store, max_wallets=1, max_pages_per_wallet=1, page_size=10,
    ))
    assert first["wallet_feed_walks_partial_or_failed"] == 1
    assert len(store.activities) == 3  # first standard page + TIP + combo feeds
    assert store.checkpoints[f"wallet_activity:activity:{W1}"]["next_cursor"] == "activity-next"
    second = asyncio.run(ingest_wallet_activity_history(
        client, store, max_wallets=1, max_pages_per_wallet=2, page_size=10,
    ))
    assert second["wallet_feed_walks_completed"] == 1  # only the previously partial standard feed
    assert len(store.activities) == 4  # resumed standard page; combo already done
    assert store.checkpoints[f"wallet_activity:activity:{W1}"]["complete"] is True
    types = {item["activity_type"] for item in store.activities.values()}
    assert types == {"DEPOSIT", "WITHDRAWAL", "TIP", "REDEEM"}
