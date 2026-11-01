from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from .polymarket import PolymarketClient
from .sessions import PaperSession, SessionState
from .store import Store


class OracleResearchAgent:
    """Live-data research loop. No independent forecast provider is assumed by default."""

    def __init__(self, client: PolymarketClient, store: Store | None = None,
                 poll_seconds: int = 30, market_limit: int = 100, book_limit: int = 20) -> None:
        self.client = client
        self.store = store
        self.poll_seconds = max(10, poll_seconds)
        self.market_limit = min(max(1, market_limit), 500)
        self.book_limit = min(max(1, book_limit), 100)
        self.session: PaperSession | None = None
        self.last_error: str | None = None
        self.last_cycle_at: datetime | None = None
        self.last_market_count = 0

    async def run_session(self, session: PaperSession) -> None:
        self.session = session
        while session.state == SessionState.RUNNING:
            try:
                markets = await self.client.markets(limit=self.market_limit, active=True)
                for market in markets:
                    if self.store:
                        await self.store.upsert_market(market)
                book_count = 0
                for market in sorted(markets, key=lambda m: float(m.get("liquidityNum") or 0), reverse=True)[:self.book_limit]:
                    token_ids = market.get("clobTokenIds") or []
                    if isinstance(token_ids, str):
                        try:
                            token_ids = json.loads(token_ids)
                        except json.JSONDecodeError:
                            token_ids = []
                    if not isinstance(token_ids, list):
                        continue
                    for token_id in token_ids[:2]:
                        try:
                            book = await self.client.order_book(str(token_id), str(market.get("id", "")))
                            if self.store:
                                await self.store.save_orderbook(book)
                            book_count += 1
                        except Exception as book_exc:
                            session.errors += 1
                            self.last_error = f"OrderBook {market.get('id')}: {type(book_exc).__name__}: {book_exc}"
                session.observations += len(markets) + book_count
                session.heartbeat_at = datetime.now(UTC)
                self.last_market_count = len(markets)
                self.last_cycle_at = session.heartbeat_at
                self.last_error = None
                if self.store:
                    await self.store.audit(
                        "MARKET_DATA_CYCLE", "agent", "paper_session", session.session_id,
                        {"markets_seen": len(markets), "orderbooks_seen": book_count, "mode": "live_data_paper_only"},
                    )
            except Exception as exc:  # fail visible, continue read-only retries
                session.errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self.store:
                    await self.store.audit("AGENT_CYCLE_ERROR", "agent", "paper_session",
                                           session.session_id, {"error": self.last_error})
            session.refresh()
            if self.store:
                await self.store.update_session(session)
            if session.state != SessionState.RUNNING:
                break
            remaining = max(0.0, (session.ends_at - datetime.now(UTC)).total_seconds())
            if remaining > 0:
                await asyncio.sleep(min(self.poll_seconds, remaining))

    def status(self) -> dict[str, Any]:
        if not self.session:
            return {"agent_state": "idle", "last_cycle_at": None,
                    "last_market_count": self.last_market_count, "last_error": self.last_error}
        self.session.refresh()
        return {
            "agent_state": self.session.state.value,
            "session_id": self.session.session_id,
            "started_at": self.session.started_at.isoformat(),
            "ends_at": self.session.ends_at.isoformat(),
            "heartbeat_at": self.session.heartbeat_at.isoformat() if self.session.heartbeat_at else None,
            "observations": self.session.observations,
            "orders_submitted": self.session.orders_submitted,
            "errors": self.session.errors,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_market_count": self.last_market_count,
            "last_error": self.last_error,
            "execution_mode": "paper",
            "autonomous_order_generation": "disabled_until_independent_forecast_provider_is_configured",
        }
