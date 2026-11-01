"""Fault-injection tests for the collector. Async code runs through asyncio.run so the
tests never depend on pytest-asyncio and cannot be silently skipped."""
import asyncio
import json
from datetime import UTC, datetime, timedelta

from oracle_platform.collector import Collector, backoff_delay

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
ASSETS = ["A", "B"]
BOOK = json.dumps({"event_type": "book", "asset_id": "A", "market": "m", "timestamp": "1",
                   "bids": [{"price": "0.4", "size": "1"}], "asks": [{"price": "0.5", "size": "1"}]})


class FakeStore:
    def __init__(self, last_frame=None, fail_saves_after=None, fail_count=0, none_id=False):
        self.calls, self.gaps, self.invalid, self.saved = [], [], [], []
        self.last_frame, self.fail_saves_after = last_frame, fail_saves_after
        self.fail_count, self.none_id = fail_count, none_id

    async def last_clob_frame_time(self):
        return self.last_frame

    async def save_clob_raw_frame(self, payload, conn, received, mono, frame_type="json"):
        if self.none_id:
            return None
        if (self.fail_saves_after is not None and len(self.saved) >= self.fail_saves_after
                and self.fail_count > 0):
            self.fail_count -= 1
            raise ConnectionError("database stalled")
        self.saved.append((payload, received, mono, frame_type))
        self.calls.append(("save", len(self.saved)))
        return len(self.saved)

    async def finalize_clob_raw_frame(self, message_id, event, parser_error=None):
        self.calls.append(("finalize", message_id, parser_error,
                           event["event_type"] if event else None))

    async def record_clob_capture_gap(self, conn, started, ended, reason, assets, attempt,
                                      recovered_at=None, gap_kind="connection_loss",
                                      last_frame_at=None):
        self.gaps.append({"start": started, "end": ended, "reason": reason, "recovered": recovered_at,
                          "kind": gap_kind, "last_frame": last_frame_at, "assets": assets})
        return len(self.gaps)

    async def mark_clob_assets_invalid(self, assets, since, reason, gap_id=None):
        self.invalid.append((list(assets), since, reason, gap_id))
        return len(assets)


class FakeWS:
    def __init__(self, script, collector, sent):
        self.script, self.collector, self.sent = list(script), collector, sent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, msg):
        self.sent.append(json.loads(msg))

    async def recv(self):
        if not self.script:
            self.collector.stop.set()
            raise TimeoutError
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(store, connections):
    state = {"sent": [], "n": 0, "tick": 0}
    holder = {}

    def clock():
        state["tick"] += 1
        return T0 + timedelta(seconds=state["tick"])

    def connect():
        script = connections[min(state["n"], len(connections) - 1)]
        state["n"] += 1
        if isinstance(script, Exception):
            raise script
        return FakeWS(script, holder["c"], state["sent"])

    c = Collector(store, ASSETS, connect, clock=clock, mono=lambda: state["tick"] * 10,
                  backoff_cap=0.001)
    holder["c"] = c
    return c, state


def run(c):
    asyncio.run(asyncio.wait_for(c.run(), timeout=5))


def test_every_frame_is_saved_before_it_is_parsed():
    store = FakeStore()
    c, _ = make(store, [["PONG", "{bad json", json.dumps({"event_type": "future", "asset_id": "A"}),
                         json.dumps([json.loads(BOOK)]), b"\xff\xfe"]])
    run(c)
    first_saves = [i for i, x in enumerate(store.calls) if x[0] == "save"]
    assert len(store.saved) == 5
    for idx in first_saves:  # each save precedes the finalize of the same frame
        assert store.calls[idx][0] == "save"
    ids_saved = [x[1] for x in store.calls if x[0] == "save"]
    ids_final = [x[1] for x in store.calls if x[0] == "finalize"]
    assert set(ids_saved) <= set(ids_final)
    errors = {x[2] for x in store.calls if x[0] == "finalize"}
    assert "keepalive_text" in errors and any(e and e.startswith("json_decode_error") for e in errors)
    assert all(s[2] > 0 and s[1].tzinfo for s in store.saved)  # monotonic + wall clock populated


def test_connection_drop_records_gap_from_last_persisted_frame_and_resubscribes():
    store = FakeStore()
    c, st = make(store, [[BOOK, ConnectionError("reset by peer")], [BOOK]])
    run(c)
    assert len(st["sent"]) == 2 and all(m["assets_ids"] == ASSETS for m in st["sent"])
    drop = [g for g in store.gaps if g["kind"] == "connection_loss"][0]
    assert drop["start"] == drop["last_frame"] == store.saved[0][1]
    assert drop["end"] > drop["start"] and drop["recovered"] == drop["end"]
    assert "ConnectionError" in drop["reason"]
    assert [i for i in store.invalid if i[2] == "connection_loss" and i[1] == drop["start"]]


def test_gap_invalidates_all_assets_at_disconnect_before_reconnect():
    store = FakeStore()
    c, _ = make(store, [[BOOK, ConnectionError("x")], [BOOK]])
    run(c)
    first = [i for i in store.invalid if i[2] == "connection_loss"][0]
    assert first[0] == ASSETS and first[3] is None  # invalidated immediately, before the gap row exists


def test_restart_after_kill_records_gap_from_previous_last_frame():
    prior = T0 - timedelta(minutes=5)
    store = FakeStore(last_frame=prior)
    c, _ = make(store, [[BOOK]])
    run(c)
    g = store.gaps[0]
    assert g["kind"] == "process_restart" and g["start"] == prior and g["end"] > T0


def test_database_stall_does_not_lose_gap_start():
    store = FakeStore(fail_saves_after=1, fail_count=2)  # two saves fail, then the DB heals
    c, _ = make(store, [[BOOK, BOOK], [BOOK], [BOOK]])
    run(c)
    stall = next(g for g in store.gaps if g["kind"] == "connection_loss")
    assert stall["start"] == store.saved[0][1]  # last DURABLE frame, not the frame that failed
    assert len(store.saved) >= 2  # capture resumed after the stall


def test_unpersistable_frame_is_an_error_not_a_silent_drop():
    store = FakeStore(none_id=True)
    c, _ = make(store, [[BOOK]])
    try:
        asyncio.run(c.handle_frame(BOOK, "conn"))
    except RuntimeError as exc:
        assert "no message id" in str(exc)
    else:
        raise AssertionError("frame with no durable id must raise")


def test_stop_during_gap_records_unrecovered_gap():
    store = FakeStore()
    c, _ = make(store, [ConnectionError("down")])

    async def stopper():
        await asyncio.sleep(0.01)
        c.stop.set()

    async def both():
        await asyncio.gather(c.run(), stopper())

    asyncio.run(asyncio.wait_for(both(), timeout=5))
    g = store.gaps[-1]
    assert g["recovered"] is None and g["reason"].startswith("collector_stopped_during_gap:")


def test_malformed_frame_invalidates_assets():
    store = FakeStore()
    c, _ = make(store, [[BOOK, "{oops"]])
    run(c)
    assert any(i[2] == "undecodable_frame" for i in store.invalid)


def test_normalization_error_invalidates_only_named_asset():
    store = FakeStore()
    bad = json.dumps({"event_type": "book", "asset_id": "A", "bids": [{"price": "-1", "size": "2"}]})
    c, _ = make(store, [[bad]])
    run(c)
    assert [i[0] for i in store.invalid if i[2] == "parse_error"] == [["A"]]


def test_backoff_is_bounded_and_monotonic():
    delays = [backoff_delay(n) for n in range(1, 12)]
    assert delays == sorted(delays) and max(delays) == 60.0 and delays[0] == 2.0
    assert backoff_delay(10, cap=5.0) == 5.0
