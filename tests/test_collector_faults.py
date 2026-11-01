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
    def __init__(self, last_frame=None, fail_saves_after=None, fail_count=0, none_id=False,
                 open_gaps=None):
        self.calls, self.invalid, self.saved, self.states = [], [], [], []
        self.gap_rows, self.parents, self.children = {}, [], []
        self.last_frame, self.fail_saves_after = last_frame, fail_saves_after
        self.fail_count, self.none_id = fail_count, none_id
        for g in open_gaps or []:
            self.gap_rows[g["gap_id"]] = {**g, "end": None, "recovered": None}

    @property
    def gaps(self):  # closed gaps, in id order, in the shape the tests assert on
        return [g for _, g in sorted(self.gap_rows.items()) if g["end"] is not None]

    async def last_clob_frame_time(self):
        return self.last_frame

    async def adopt_open_clob_gap(self):
        opened = [g for g in self.gap_rows.values() if g["end"] is None]
        return min(opened, key=lambda g: g["start"]) if opened else None

    async def save_clob_raw_frame(self, payload, conn, received, mono, frame_type="json",
                                  parent_message_id=None, item_index=None):
        if self.none_id:
            return None
        if (self.fail_saves_after is not None and len(self.saved) >= self.fail_saves_after
                and self.fail_count > 0):
            self.fail_count -= 1
            raise ConnectionError("database stalled")
        self.saved.append((payload, received, mono, frame_type))
        if parent_message_id is not None:
            self.children.append((payload, parent_message_id, item_index))
        self.calls.append(("save", len(self.saved)))
        return len(self.saved)

    async def finalize_clob_array_parent(self, message_id, item_count):
        self.parents.append((message_id, item_count))

    async def finalize_clob_raw_frame(self, message_id, event, parser_error=None):
        self.calls.append(("finalize", message_id, parser_error,
                           event["event_type"] if event else None))

    async def open_clob_capture_gap(self, conn, started, reason, assets, attempt, kind, last_frame):
        gid = len(self.gap_rows) + 1
        self.gap_rows[gid] = {"gap_id": gid, "start": started, "end": None, "reason": reason,
                              "recovered": None, "kind": kind, "last_frame": last_frame,
                              "assets": assets, "started_at": started}
        return gid

    async def close_clob_capture_gap(self, gap_id, ended_at, reason, recovered_at):
        g = self.gap_rows[gap_id]
        g.update(end=ended_at, reason=reason, recovered=recovered_at)

    async def set_clob_connection_state(self, state, at, gap_id=None, detail=None):
        self.states.append(state)

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


def make(store, connections, stable_after_ns=60_000_000_000):
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
                  backoff_cap=0.001, stable_after_ns=stable_after_ns)
    holder["c"] = c
    return c, state


def run(c):
    asyncio.run(asyncio.wait_for(c.run(), timeout=5))


def test_every_frame_is_saved_before_it_is_parsed():
    store = FakeStore()
    c, _ = make(store, [["PONG", "{bad json", json.dumps({"event_type": "future", "asset_id": "A"}),
                         json.dumps([json.loads(BOOK)]), b"\xff\xfe"]])
    run(c)
    assert len(store.saved) == 6  # 5 raw frames + 1 child row of the array frame
    assert sum(1 for x in store.saved if x[3] != "json_array_item") == 5
    saved_so_far = set()
    for call in store.calls:  # a frame id must be durable before anything finalizes it
        if call[0] == "save":
            saved_so_far.add(call[1])
        else:
            assert call[1] in saved_so_far
    finalized = {x[1] for x in store.calls if x[0] == "finalize"} | {p for p, _ in store.parents}
    assert saved_so_far == finalized  # nothing archived is left unresolved
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
    assert "interrupted" in store.states and "recovering" in store.states
    assert "healthy" not in store.states  # a reconnect alone never declares the feed healthy


def test_gap_invalidates_all_assets_at_disconnect_before_reconnect():
    store = FakeStore()
    c, _ = make(store, [[BOOK, ConnectionError("x")], [BOOK]])
    run(c)
    first = [i for i in store.invalid if i[2] == "connection_loss"][0]
    assert first[0] == ASSETS and first[3] is not None  # invalidated against an already-persisted open gap


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


def test_open_gap_is_persisted_before_reconnect_and_survives_a_crash():
    store = FakeStore()
    c, _ = make(store, [[BOOK, ConnectionError("x")], [BOOK]])
    snapshots = []
    orig = store.mark_clob_assets_invalid

    async def spy(assets, since, reason, gap_id=None):
        snapshots.append({k: dict(v) for k, v in store.gap_rows.items()})
        return await orig(assets, since, reason, gap_id)

    store.mark_clob_assets_invalid = spy
    run(c)
    during = next(sn for sn in snapshots if any(g["end"] is None and g["kind"] == "connection_loss"
                                                for g in sn.values()))
    open_rows = [g for g in during.values() if g["end"] is None and g["kind"] == "connection_loss"]
    assert open_rows and open_rows[0]["start"] == store.saved[0][1]


def test_restart_adopts_orphaned_open_gap_and_keeps_its_earlier_start():
    orphan_start = T0 - timedelta(minutes=30)
    store = FakeStore(last_frame=T0 - timedelta(minutes=29),
                      open_gaps=[{"gap_id": 7, "start": orphan_start, "kind": "connection_loss",
                                  "reason": "x", "assets": ASSETS, "last_frame": None,
                                  "started_at": orphan_start}])
    c, _ = make(store, [[BOOK]])
    run(c)
    assert len(store.gap_rows) == 1  # adopted, not duplicated
    g = store.gap_rows[7]
    assert g["start"] == orphan_start and g["end"] is not None


def test_flapping_connection_escalates_backoff_and_does_not_reset():
    store = FakeStore()
    drops = [[BOOK, ConnectionError("flap")] for _ in range(5)] + [[BOOK]]
    c, _ = make(store, drops)  # each connection lives far less than 60s
    run(c)
    assert c.delays == sorted(c.delays) and len(c.delays) == 5
    assert c.failures == 5  # five unstable connections in a row: the counter must not reset
    assert backoff_delay(5) > backoff_delay(1)  # un-capped schedule really escalates


def test_stable_connection_resets_failure_count():
    store = FakeStore()
    c, _ = make(store, [[ConnectionError("a")], [ConnectionError("b")], [BOOK, ConnectionError("c")], [BOOK]],
                stable_after_ns=1)  # any connection that lived at all counts as stable
    run(c)
    assert c.failures == 1  # 2 failures, then a stable session dropped -> counter restarted


def test_array_frame_payload_is_stored_once_with_child_references():
    store = FakeStore()
    arr = json.dumps([json.loads(BOOK), json.loads(BOOK)])
    c, _ = make(store, [[arr]])
    run(c)
    assert store.parents == [(1, 2)]
    full_copies = [p for p, *_ in store.saved if isinstance(p, str) and "bids" in p]
    assert len(full_copies) == 1  # only the parent holds the payload
    assert [(ref["$ref_message_id"], ref["index"]) for ref, _, _ in store.children] == [(1, 0), (1, 1)]
