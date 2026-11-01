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
                 backoff_cap: float = 60.0, recv_timeout: float = 1.0) -> None:
        self.store = store
        self.assets = list(dict.fromkeys(assets))
        self.connect = connect
        self.clock = clock
        self.mono = mono
        self.backoff_cap = backoff_cap
        self.recv_timeout = recv_timeout
        self.last_frame_at: datetime | None = None
        self.gap_start: datetime | None = None
        self.gap_reason = ""
        self.gap_kind = "connection_loss"
        self.gap_connection_id: str | None = None
        self.failures = 0
        self.stop = asyncio.Event()

    # ---- gap bookkeeping -------------------------------------------------
    async def _open_gap(self, since: datetime, reason: str, kind: str, connection_id: str) -> None:
        """Start (or keep) a gap and invalidate every asset from the last persisted frame."""
        if self.gap_start is None:
            self.gap_start, self.gap_reason = since, reason
            self.gap_kind, self.gap_connection_id = kind, connection_id
        try:
            await self.store.mark_clob_assets_invalid(self.assets, self.gap_start, self.gap_kind)
        except Exception:  # DB may be the very thing that failed; closed again on recovery
            pass

    async def _close_gap(self, ended_at: datetime, recovered: bool) -> None:
        if self.gap_start is None:
            return
        reason = self.gap_reason if recovered else "collector_stopped_during_gap:" + self.gap_reason
        gap_id = await self.store.record_clob_capture_gap(
            self.gap_connection_id or "unknown", self.gap_start, ended_at, reason, self.assets,
            max(self.failures, 1), recovered_at=ended_at if recovered else None,
            gap_kind=self.gap_kind, last_frame_at=self.last_frame_at,
        )
        await self.store.mark_clob_assets_invalid(self.assets, self.gap_start, self.gap_kind, gap_id)
        self.gap_start = None

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
        for index, message in enumerate(messages):
            event, parse_error = None, None
            try:
                event = normalize_market_message(message, received, connection_id)
                event["received_monotonic_ns"] = mono
            except Exception as exc:  # keep raw evidence, invalidate the asset, continue
                parse_error = f"normalization_error:{type(exc).__name__}:{exc}"
            target = raw_id if index == 0 else await self.store.save_clob_raw_frame(
                message, connection_id, received, mono, "json_array_item")
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
        await self._open_gap(last or startup, "process_start", "process_restart", "startup")
        while not self.stop.is_set():
            connection_id = str(uuid.uuid4())
            try:
                async with self.connect() as ws:
                    await ws.send(json.dumps({"type": "market", "assets_ids": self.assets,
                                              "custom_feature_enabled": True}))
                    await self._close_gap(self.clock(), recovered=True)
                    self.failures = 0
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
                self.failures += 1
                await self._open_gap(self.last_frame_at or self.clock(),
                                     f"{type(exc).__name__}:{exc}"[:500], "connection_loss",
                                     connection_id)
                try:
                    await asyncio.wait_for(self.stop.wait(),
                                           timeout=backoff_delay(self.failures, self.backoff_cap))
                except TimeoutError:
                    pass
        if self.gap_start is not None:
            await self._close_gap(self.clock(), recovered=False)
