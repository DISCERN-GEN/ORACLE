import asyncio

from oracle_platform.polymarket import PolymarketClient


def test_leaderboard_cursor_request_does_not_repeat_bound_filters():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.leaderboard(limit=250, time_period="all", cursor="opaque-cursor"))
    assert captured["url"].endswith("/v2/leaderboard")
    assert captured["params"] == {"cursor": "opaque-cursor"}


def test_first_leaderboard_page_sets_board_filters():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.leaderboard(limit=250, time_period="all"))
    assert captured["params"] == {
        "limit": 250, "time_period": "all", "category": "overall", "sort_by": "PNL"
    }


def test_wallet_trades_resume_with_user_anchor_and_cursor():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.wallet_trades("0xabc", limit=250, cursor="cursor-2"))
    assert captured["url"].endswith("/v2/trades")
    assert captured["params"] == {
        "user": "0xabc", "limit": 250, "cursor": "cursor-2",
        "start": 1, "taker_only": "false", "filter_type": "TOKENS",
        "filter_amount": 0.00000001,
    }


def test_get_retries_rate_limit_then_succeeds():
    import httpx

    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "busy"})
        return httpx.Response(200, json={"ok": True})

    async def run():
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = PolymarketClient(http, max_retries=2)
        result = await client._get("https://example.test/data")
        await http.aclose()
        return result

    assert asyncio.run(run()) == {"ok": True}
    assert calls["count"] == 2


def test_market_trade_feed_batches_conditions_and_preserves_cursor():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    conditions = ["0x" + str(i).zfill(64) for i in range(2)]
    asyncio.run(client.market_trades(conditions, limit=750, cursor="opaque"))
    assert captured["url"].endswith("/v2/trades")
    assert captured["params"] == {
        "condition": ",".join(conditions), "limit": 750, "cursor": "opaque",
        "taker_only": "false", "filter_type": "TOKENS", "filter_amount": 0.00000001,
    }


def test_wallet_activity_requests_full_history_and_includes_deposits_withdrawals():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.wallet_activity("0xabc", limit=700, cursor="opaque-activity"))
    assert captured["url"].endswith("/v2/activity")
    assert captured["params"] == {
        "user": "0xabc", "limit": 700, "start": 1,
        "exclude_deposits_withdrawals": "false", "sort_by": "TIMESTAMP",
        "sort_direction": "DESC", "cursor": "opaque-activity",
    }


def test_wallet_combo_activity_uses_distinct_feed_and_cursor():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["url"] = url
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.wallet_combo_activity("0xabc", limit=500, cursor="combo-cursor"))
    assert captured["url"].endswith("/v2/activity/combos")
    assert captured["params"] == {"user": "0xabc", "limit": 500, "cursor": "combo-cursor"}


def test_wallet_activity_can_opt_in_to_tip_events():
    client = PolymarketClient()
    captured = {}

    async def fake_get(url, params=None):
        captured["params"] = params
        return {"data": [], "pagination": {"next_cursor": None}}

    client._get = fake_get  # type: ignore[method-assign]
    asyncio.run(client.wallet_activity("0xabc", activity_type="TIP"))
    assert captured["params"]["type"] == "TIP"
    assert captured["params"]["start"] == 1
    assert captured["params"]["exclude_deposits_withdrawals"] == "false"
