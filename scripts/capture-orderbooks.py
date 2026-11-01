#!/usr/bin/env python3
"""Public Polymarket CLOB capture. Thin wrapper: all logic lives in oracle_platform.collector."""
from __future__ import annotations

import asyncio
import os
import signal

from oracle_platform.collector import URL, Collector
from oracle_platform.settings import settings
from oracle_platform.store import Store


def _connect():
    import websockets  # imported lazily so the collector module stays testable without it

    return websockets.connect(URL, ping_interval=20, ping_timeout=20, max_size=8 * 1024 * 1024,
                              open_timeout=20, close_timeout=5)


async def main() -> None:
    assets = [x.strip() for x in os.getenv("ASSET_IDS", "").split(",") if x.strip()]
    if not assets:
        raise SystemExit("Set ASSET_IDS to comma-separated CLOB outcome token IDs")
    store = Store(settings.database_url)
    await store.connect()
    if not await store.health():
        raise RuntimeError("PostgreSQL is not healthy")
    for version in ("004_orderbook_capture", "005_capture_validity", "006_capture_health"):
        await store.require_schema(version)
    collector = Collector(store, assets, _connect)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, collector.stop.set)
    try:
        await collector.run()
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
