from __future__ import annotations

import argparse
import asyncio

from .agent import OracleResearchAgent
from .polymarket import PolymarketClient
from .sessions import PaperSession
from .settings import settings
from .store import Store


async def run(hours: int) -> None:
    store = Store(settings.database_url)
    await store.connect()
    client = PolymarketClient()
    session = PaperSession.start(hours)
    await store.start_session(session, str(settings.paper_initial_bankroll))
    try:
        agent = OracleResearchAgent(client, store)
        await agent.run_session(session)
        print({"session_id": session.session_id, "state": session.state.value,
               "observations": session.observations, "errors": session.errors})
    finally:
        await client.close()
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an ORACLE live-data / paper-only test session")
    parser.add_argument("--hours", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.hours <= 24:
        parser.error("--hours must be between 1 and 24")
    asyncio.run(run(args.hours))


if __name__ == "__main__":
    main()
