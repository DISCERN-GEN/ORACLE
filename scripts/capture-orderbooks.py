#!/usr/bin/env python3
"""Resilient public Polymarket CLOB capture with raw-first persistence and gap logs."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from datetime import datetime, timezone
from time import monotonic_ns

import websockets
from websockets.exceptions import ConnectionClosed

from oracle_platform.book_capture import decode_market_frame, normalize_market_message
from oracle_platform.settings import settings
from oracle_platform.store import Store

URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)



async def main() -> None:
    assets = list(dict.fromkeys(x.strip() for x in os.getenv("ASSET_IDS", "").split(",") if x.strip()))
    if not assets:
        raise SystemExit("Set ASSET_IDS to comma-separated CLOB outcome token IDs")
    store = Store(settings.database_url)
    await store.connect()
    if not await store.health():
        raise RuntimeError("PostgreSQL is not healthy")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    attempt = 0
    gap_started: datetime | None = None
    gap_reason = "initial_connection"
    gap_connection_id: str | None = None
    try:
        while not stop.is_set():
            attempt += 1
            connection_id = str(uuid.uuid4())
            connected_at = utcnow()
            try:
                async with websockets.connect(
                    URL, ping_interval=20, ping_timeout=20, max_size=8 * 1024 * 1024,
                    open_timeout=20, close_timeout=5,
                ) as ws:
                    await ws.send(json.dumps({
                        "type": "market", "assets_ids": assets, "custom_feature_enabled": True,
                    }))
                    if gap_started is not None:
                        await store.record_clob_capture_gap(
                            gap_connection_id or connection_id, gap_started, connected_at,
                            gap_reason, assets, max(attempt, 1), recovered_at=connected_at,
                        )
                        gap_started = None
                        gap_connection_id = None
                    attempt = 0
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        received = utcnow()
                        mono = monotonic_ns()
                        frame_type = "text" if isinstance(raw, str) else "binary"
                        raw_id = await store.save_clob_raw_frame(
                            raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw,
                            connection_id, received, mono, frame_type,
                        )
                        if raw_id is None:
                            raise RuntimeError("raw frame persistence returned no message id")

                        decoded, decode_error = decode_market_frame(raw)
                        if decode_error:
                            await store.finalize_clob_raw_frame(raw_id, None, decode_error)
                            continue
                        if isinstance(decoded, str):  # plain-text keepalive / status frame
                            await store.finalize_clob_raw_frame(raw_id, None, "plain_text_frame")
                            continue
                        messages = decoded if isinstance(decoded, list) else [decoded]
                        dict_messages = [m for m in messages if isinstance(m, dict)]
                        if not dict_messages:
                            await store.finalize_clob_raw_frame(raw_id, None, "json_frame_without_event_objects")
                            continue
                        for index, message in enumerate(dict_messages):
                            event = None
                            parse_error = None
                            try:
                                event = normalize_market_message(message, received, connection_id)
                                event["received_monotonic_ns"] = mono
                            except Exception as exc:  # retain raw evidence and continue
                                parse_error = f"normalization_error:{type(exc).__name__}:{exc}"
                            target_id = raw_id if index == 0 else await store.save_clob_raw_frame(
                                message, connection_id, received, mono, "json_array_item",
                            )
                            await store.finalize_clob_raw_frame(target_id, event, parse_error)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop.is_set():
                    break
                now = utcnow()
                if gap_started is None:
                    gap_started = now
                    gap_connection_id = connection_id
                gap_reason = f"{type(exc).__name__}:{exc}"[:500]
                delay = min(60.0, 2.0 ** min(attempt, 6))
                if not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
        if gap_started is not None:
            await store.record_clob_capture_gap(
                gap_connection_id or connection_id, gap_started, utcnow(), "collector_stopped_during_gap:" + gap_reason,
                assets, max(attempt, 1), recovered_at=None,
            )
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
