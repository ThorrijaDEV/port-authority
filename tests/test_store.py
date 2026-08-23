from __future__ import annotations

import pytest

from port_authority.model import Change, make_listener
from port_authority.store import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "history.db")
    yield s
    s.close()


def add(store: Store, kind: str, ts: float, **kw) -> None:
    store.record_changes([Change(kind=kind, ts=ts, listener=make_listener(**kw))], ts)


class TestRecordAndQuery:
    def test_record_and_count(self, store):
        add(store, "open", 100.0, port=80)
        add(store, "close", 200.0, port=80)
        assert store.count_events() == 2

    def test_filters(self, store):
        add(store, "open", 100.0, port=80)
        add(store, "open", 150.0, port=443)
        add(store, "close", 200.0, port=80)

        assert len(list(store.iter_events(port=80))) == 2
        assert len(list(store.iter_events(kind="close"))) == 1
        window = list(store.iter_events(since=120, until=180))
        assert [e.listener.port for e in window] == [443]

    def test_ordering_and_reverse(self, store):
        add(store, "open", 300.0, port=22)
        add(store, "open", 100.0, port=80)
        forward = [e.ts for e in store.iter_events()]
        backward = [e.ts for e in store.iter_events(reverse=True)]
        assert forward == sorted(forward)
        assert backward == sorted(backward, reverse=True)

    def test_roundtrip_preserves_fields(self, store):
        listener = make_listener(port=5432, pid=4242, process="postgres",
                                 proto="tcp6", address="::1", started_at=99.5)
        store.record_changes([Change(kind="open", ts=7.0, listener=listener)], 7.0)
        event = next(iter(store.iter_events()))
        assert event.kind == "open"
        assert event.ts == 7.0
        got = event.listener
        assert (got.port, got.pid, got.process, got.proto, got.address, got.started_at) == (
            5432, 4242, "postgres", "tcp6", "::1", 99.5,
        )


class TestReplayState:
    def test_replay_reconstructs_state(self, store):
        add(store, "open", 1.0, port=80)
        add(store, "open", 2.0, port=443)
        add(store, "close", 3.0, port=80)
        state = store.replay_state()
        keys = {k.port for k in state}
        assert keys == {443}

    def test_replay_until_point_in_time(self, store):
        add(store, "open", 1.0, port=80)
        add(store, "close", 3.0, port=80)
        early = {k.port for k in store.replay_state(until=2.0)}
        late = {k.port for k in store.replay_state(until=9.0)}
        assert early == {80}
        assert late == set()

    def test_replay_across_restart_simulation(self, store):
        # Watch session one.
        add(store, "open", 1.0, port=8080)
        # Process died while nobody was watching; session two records the close.
        add(store, "close", 50.0, port=8080)
        state = store.replay_state()
        assert state == {}

    def test_meta_roundtrip(self, store):
        assert store.get_meta("missing") is None
        store.set_meta("k", "v1")
        store.set_meta("k", "v2")
        assert store.get_meta("k") == "v2"


def test_store_creates_parent_dirs(tmp_path):
    deep = tmp_path / "a" / "b" / "history.db"
    Store(deep).close()
    assert deep.exists()


def test_invalid_kind_rejected_by_schema(tmp_path):
    import sqlite3

    store = Store(tmp_path / "x.db")
    with pytest.raises(sqlite3.IntegrityError):
        bad = make_listener(port=1)
        store.conn.execute(
            "INSERT INTO events (ts, kind, proto, port, address, pid, process, proc_started)"
            " VALUES (1.0, 'explode', 'tcp', 1, '0.0.0.0', NULL, NULL, NULL)"
        )
    store.close()
