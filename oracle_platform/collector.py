"""CLOB market-channel collector with injected dependencies so faults can be tested.

Guarantees: every frame is persisted raw before parsing; every interval in which
frames may have been missed is recorded as a gap and the affected assets are
invalid until a fresh full book snapshot arrives. Nothing here signs or trades.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic_ns
from typing import Any

from oracle_platform.book_capture import decode_market_frame, normalize_market_message

URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
KEEPALIVE_TEXTS = {"PONG", "PING", ""}


def utcnow() -> datetime:
    return datetime.now(UTC)


def backoff_delay(attempt: int, cap: float = 60.0) -> float:
    """Bounded exponential backoff: 2, 4, ... capped; attempt counts consecutive failures."""
    return min(cap, 2.0 ** min(max(attempt, 1), 6))


class Collector:
    def __init__(self, store: Any, assets: list[str],
                 connect: Callable[[], Any],
                 clock: Callable[[], datetime] = utcnow,
                 mono: Callable[[], int] = monotonic_ns,
                 backoff_cap: float = 60.0, recv_timeout: float = 1.0,
                 stable_after_ns: int = 60_000_000_000) -> None:
        self.store = store
        self.assets = list(dict.fromkeys(assets))
        self.connect = connect
        self.clock = clock
        self.mono = mono
        self.backoff_cap = backoff_cap
        self.recv_timeout = recv_timeout
        self.stable_after_ns = stable_after_ns
        self.delays: list[float] = []
        self.gap_id: int | None = None
        self.last_frame_at: datetime | None = None
        self.gap_start: datetime | None = None
        self.gap_reason = ""
        self.gap_kind = "connection_loss"
        self.gap_connection_id: str | None = None
        self.failures = 0
        self.stop = asyncio.Event()

    # ---- gap bookkeeping -------------------------------------------------
    async def _open_gap(self, since: datetime, reason: str, kind: str, connection_id: str,
                        adopted: dict | None = None) -> None:
        """Persist the gap as OPEN first, then invalidate assets from the last persisted frame."""
        if self.gap_start is None:
            self.gap_start, self.gap_reason = since, reason
            self.gap_kind, self.gap_connection_id = kind, connection_id
            try:
                if adopted:
                    self.gap_id = adopted["gap_id"]
                else:
                    self.gap_id = await self.store.open_clob_capture_gap(
                        connection_id, since, reason, self.assets, max(self.failures, 1), kind,
                        self.last_frame_at)
            except Exception:  # DB may be the failure; the gap is re-derived from last frame on restart
                self.gap_id = None
        try:
            await self.store.mark_clob_assets_invalid(
                self.assets, self.gap_start, self.gap_kind, self.gap_id)
            await self.store.set_clob_connection_state(
                "interrupted", self.gap_start, self.gap_id, self.gap_reason[:200])
        except Exception:
            pass

    async def _close_gap(self, ended_at: datetime, recovered: bool) -> None:
        """Close the gap. A reconnect is only 'recovering': assets stay invalid until a fresh book."""
        if self.gap_start is None:
            return
        reason = self.gap_reason if recovered else "collector_stopped_during_gap:" + self.gap_reason
        if self.gap_id is None:  # the open write failed earlier (DB down): write it complete now
            self.gap_id = await self.store.open_clob_capture_gap(
                self.gap_connection_id or "unknown", self.gap_start, reason, self.assets,
                max(self.failures, 1), self.gap_kind, self.last_frame_at)
        await self.store.close_clob_capture_gap(
            self.gap_id, ended_at, reason, ended_at if recovered else None)
        await self.store.mark_clob_assets_invalid(self.assets, self.gap_start, self.gap_kind, self.gap_id)
        if recovered:
            await self.store.set_clob_connection_state("recovering", ended_at, self.gap_id, reason[:200])
        self.gap_start, self.gap_id = None, None

    # ---- frame handling ---------------------------------------------------
    async def handle_frame(self, raw: str | bytes, connection_id: str) -> None:
        received, mono = self.clock(), self.mono()
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        frame_type = "text" if isinstance(raw, str) else "binary"
        raw_id = await self.store.save_clob_raw_frame(text, connection_id, received, mono, frame_type)
        if raw_id is None:
            raise RuntimeError("raw frame persistence returned no message id")
        self.last_frame_at = received  # only after the raw frame is durable

        if text.strip() in KEEPALIVE_TEXTS:
            await self.store.finalize_clob_raw_frame(raw_id, None, "keepalive_text")
            return
        decoded, error = decode_market_frame(text)
        if error:
            await self.store.finalize_clob_raw_frame(raw_id, None, error)
            await self.store.mark_clob_assets_invalid(self.assets, received, "undecodable_frame")
            return
        items = decoded if isinstance(decoded, list) else [decoded]
        messages = [m for m in items if isinstance(m, dict)]
        if not messages:
            await self.store.finalize_clob_raw_frame(raw_id, None, "json_frame_without_event_objects")
            return
        is_array = isinstance(decoded, list)
        if is_array:
            await self.store.finalize_clob_array_parent(raw_id, len(messages))
        for index, message in enumerate(messages):
            event, parse_error = None, None
            try:
                event = normalize_market_message(message, received, connection_id)
                event["received_monotonic_ns"] = mono
            except Exception as exc:  # keep raw evidence, invalidate the asset, continue
                parse_error = f"normalization_error:{type(exc).__name__}:{exc}"
            if is_array:  # child row references the parent frame; payload is not copied
                target = await self.store.save_clob_raw_frame(
                    {"$ref_message_id": raw_id, "index": index}, connection_id, received, mono,
                    "json_array_item", parent_message_id=raw_id, item_index=index)
            else:
                target = raw_id
            await self.store.finalize_clob_raw_frame(target, event, parse_error)
            if parse_error is not None:
                asset = message.get("asset_id")
                await self.store.mark_clob_assets_invalid(
                    [str(asset)] if asset and str(asset) in self.assets else self.assets,
                    received, "parse_error")
            elif event is not None and not event.get("parse_valid"):
                asset = event.get("asset_id")
                if asset and asset in self.assets:
                    await self.store.mark_clob_assets_invalid([asset], received, "unknown_message_type")

    # ---- main loop --------------------------------------------------------
    async def run(self) -> None:
        # Any start is a possible gap: frames since the last persisted one were not seen.
        startup = self.clock()
        last = await self.store.last_clob_frame_time()
        if last is not None:
            self.last_frame_at = last
        orphan = await self.store.adopt_open_clob_gap()
        since = min([t for t in (last, orphan["started_at"] if orphan else None) if t] or [startup])
        await self._open_gap(since, "process_start", "process_restart", "startup", adopted=orphan)
        while not self.stop.is_set():
            connection_id = str(uuid.uuid4())
            connected_mono: int | None = None
            try:
                async with self.connect() as ws:
                    await ws.send(json.dumps({"type": "market", "assets_ids": self.assets,
                                              "custom_feature_enabled": True}))
                    await self._close_gap(self.clock(), recovered=True)
                    connected_mono = self.mono()
                    while not self.stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=self.recv_timeout)
                        except TimeoutError:
                            continue
                        await self.handle_frame(raw, connection_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self.stop.is_set():
                    break
                if connected_mono is not None and self.mono() - connected_mono >= self.stable_after_ns:
                    self.failures = 0  # only a meaningfully stable connection resets backoff
                connected_mono = None
                self.failures += 1
                await self._open_gap(self.last_frame_at or self.clock(),
                                     f"{type(exc).__name__}:{exc}"[:500], "connection_loss",
                                     connection_id)
                delay = backoff_delay(self.failures, self.backoff_cap)
                self.delays.append(delay)
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
        if self.gap_start is not None:
            await self._close_gap(self.clock(), recovered=False)
