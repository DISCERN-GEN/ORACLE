from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from .domain import BookLevel, OrderBook
from .settings import settings


class PolymarketClient:
    """Public, read-only adapters. There is intentionally no order-signing method."""

    def __init__(self, client: httpx.AsyncClient | None = None, max_retries: int = 3) -> None:
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0))
        self._owns_client = client is None
        self.max_retries = max(0, min(max_retries, 5))
        self._semaphore = asyncio.Semaphore(8)
        self._rate_lock = asyncio.Lock()
        # Shared conservative public-API pacing (about 16.7 requests/second),
        # below the documented 20 req/s activity-feed ceiling.
        self._minimum_request_interval = 0.06
        self._last_request_monotonic = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(self.max_retries + 1):
                try:
                    async with self._rate_lock:
                        now = time.monotonic()
                        wait_for = self._last_request_monotonic + self._minimum_request_interval - now
                        if wait_for > 0:
                            await asyncio.sleep(wait_for)
                        self._last_request_monotonic = time.monotonic()
                    response = await self._client.get(
                        url, params=params, headers={"User-Agent": "ORACLE-private/0.5"})
                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        if attempt >= self.max_retries:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
                        except ValueError:
                            delay = 0.5 * (2 ** attempt)
                        await asyncio.sleep(min(max(delay, 0.0), 20.0))
                        continue
                    response.raise_for_status()
                    return response.json()
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise
                    await asyncio.sleep(min(0.5 * (2 ** attempt), 8.0))
            if last_error:
                raise last_error
        raise RuntimeError("GET retry loop terminated unexpectedly")

    async def markets(self, limit: int = 100, offset: int = 0, active: bool = True) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500 or offset < 0:
            raise ValueError("Gamma pagination: limit must be 1..500 and offset >= 0")
        data = await self._get(
            f"{settings.gamma_url}/markets",
            {"active": str(active).lower(), "closed": "false", "limit": limit, "offset": offset},
        )
        if not isinstance(data, list):
            raise ValueError("Unexpected Gamma markets response")
        return data

    async def market(self, market_id: str) -> dict[str, Any]:
        data = await self._get(f"{settings.gamma_url}/markets/{quote(market_id, safe='')}")
        if not isinstance(data, dict):
            raise ValueError("Unexpected Gamma market response")
        return data

    async def order_book(self, token_id: str, market_id: str = "") -> OrderBook:
        raw = await self._get(f"{settings.clob_url}/book", {"token_id": token_id})
        # Record local receipt time. Venue payload timestamp units are not relied on
        # for freshness; an unknown/millisecond timestamp must never look fresh by accident.
        now = datetime.now(timezone.utc)
        bids = tuple(BookLevel(Decimal(x["price"]), Decimal(x["size"])) for x in raw.get("bids", []))
        asks = tuple(BookLevel(Decimal(x["price"]), Decimal(x["size"])) for x in raw.get("asks", []))
        return OrderBook(
            market_id=market_id or str(raw.get("market", "")),
            token_id=token_id,
            bids=bids,
            asks=asks,
            captured_at=now,
            tick_size=Decimal(str(raw.get("tick_size", "0.01"))),
            min_order_size=Decimal(str(raw.get("min_order_size", "1"))),
        )

    async def leaderboard(self, limit: int = 100, time_period: str = "all", cursor: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("Leaderboard limit must be 1..500")
        # v2 board cursors bind the board cohort. Resume with the opaque cursor
        # alone rather than restating board filters and risking a conflicting page.
        params: dict[str, Any]
        if cursor:
            params = {"cursor": cursor}
        else:
            params = {"limit": limit, "time_period": time_period,
                      "category": "overall", "sort_by": "PNL"}
        data = await self._get(f"{settings.data_url}/v2/leaderboard", params)
        if not isinstance(data, dict):
            raise ValueError("Unexpected leaderboard response")
        return data

    async def wallet_trades(self, wallet: str, limit: int = 100,
                            cursor: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 1000:
            raise ValueError("Trade page size must be 1..1000")
        # start=1 explicitly requests full user trade history rather than the API's
        # default three-year window. Include maker rows to avoid taker-only bias.
        params: dict[str, Any] = {"user": wallet, "limit": limit, "start": 1,
                                  "taker_only": "false", "filter_type": "TOKENS",
                                  "filter_amount": 0.00000001}
        if cursor:
            params["cursor"] = cursor
        data = await self._get(f"{settings.data_url}/v2/trades", params)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Unexpected Data API v2 wallet trades response")
        return data

    async def market_trades(self, conditions: list[str], limit: int = 1000,
                            cursor: str | None = None) -> dict[str, Any]:
        if not conditions or len(conditions) > 20:
            raise ValueError("Trade discovery requires 1..20 condition IDs per request")
        if not 1 <= limit <= 1000:
            raise ValueError("Trade page size must be 1..1000")
        params: dict[str, Any] = {
            "condition": ",".join(conditions), "limit": limit,
            "taker_only": "false", "filter_type": "TOKENS", "filter_amount": 0.00000001,
        }
        if cursor:
            params["cursor"] = cursor
        data = await self._get(f"{settings.data_url}/v2/trades", params)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Unexpected Data API v2 market trades response")
        return data

    async def wallet_activity(self, wallet: str, limit: int = 1_000,
                              cursor: str | None = None, activity_type: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 1_000:
            raise ValueError("Activity page size must be 1..1000")
        # start=1 requests the full available history. Withdrawals/deposits are
        # excluded by default, so explicitly disable that exclusion. Keep every
        # filter stable while replaying the opaque keyset cursor.
        params: dict[str, Any] = {
            "user": wallet, "limit": limit, "start": 1,
            "exclude_deposits_withdrawals": "false",
            "sort_by": "TIMESTAMP", "sort_direction": "DESC",
        }
        if activity_type:
            params["type"] = activity_type
        if cursor:
            params["cursor"] = cursor
        data = await self._get(f"{settings.data_url}/v2/activity", params)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Unexpected Data API v2 wallet activity response")
        return data

    async def wallet_combo_activity(self, wallet: str, limit: int = 1_000,
                                    cursor: str | None = None) -> dict[str, Any]:
        if not 1 <= limit <= 1_000:
            raise ValueError("Combo activity page size must be 1..1000")
        params: dict[str, Any] = {"user": wallet, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        data = await self._get(f"{settings.data_url}/v2/activity/combos", params)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Unexpected Data API v2 wallet combo activity response")
        return data

    async def geoblock(self) -> dict[str, Any]:
        data = await self._get(settings.geoblock_url)
        if not isinstance(data, dict) or "blocked" not in data:
            raise ValueError("Geoblock response missing required `blocked` field")
        return data
