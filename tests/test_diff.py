from __future__ import annotations

import pytest

from port_authority.diff import apply_changes, diff_state
from port_authority.model import Change, Listener, make_listener


def state(*listeners: Listener):
    return {l.key(): l for l in listeners}


class TestDiffState:
    def test_no_change(self):
        a = state(make_listener(80), make_listener(443, pid=101))
        b = state(make_listener(80), make_listener(443, pid=101))
        assert diff_state(a, b) == []

    def test_open_and_close(self):
        prev = state(make_listener(80))
        curr = state(make_listener(8080))
        changes = diff_state(prev, curr)
        kinds = {(c.kind, c.listener.port) for c in changes}
        assert kinds == {("open", 8080), ("close", 80)}

    def test_same_port_different_address_is_two_events(self):
        prev = state(make_listener(5432, address="127.0.0.1"))
        curr = state(make_listener(5432, address="0.0.0.0"))
        changes = diff_state(prev, curr)
        assert sorted(c.kind for c in changes) == ["close", "open"]

    def test_pid_or_process_change_is_not_an_event(self):
        # Same socket identity; only metadata changed.
        prev = state(make_listener(8080, pid=100, process="old"))
        curr = state(make_listener(8080, pid=200, process="new"))
        assert diff_state(prev, curr) == []

    def test_proto_distinguishes_sockets(self):
        prev = state(make_listener(53, proto="tcp", address="0.0.0.0"))
        curr = state(
            make_listener(53, proto="tcp", address="0.0.0.0"),
            make_listener(53, proto="udp", address="0.0.0.0"),
        )
        changes = diff_state(prev, curr)
        assert len(changes) == 1 and changes[0].kind == "open"

    def test_sorted_by_port(self):
        prev = state()
        curr = state(
            make_listener(9999),
            make_listener(22),
            make_listener(443),
        )
        ports = [c.listener.port for c in diff_state(prev, curr)]
        assert ports == [22, 443, 9999]


class TestApplyChanges:
    def test_roundtrip(self):
        base = state(make_listener(80))
        opened = Change(kind="open", ts=1.0, listener=make_listener(8080))
        closed = Change(kind="close", ts=2.0, listener=make_listener(80))
        result = apply_changes(base, [opened, closed])
        assert list(result) == [Listener.key(make_listener(8080))]

    def test_close_of_unknown_key_is_noop(self):
        base = state(make_listener(80))
        ghost = Change(kind="close", ts=1.0, listener=make_listener(1234))
        assert apply_changes(base, [ghost]) == base

    def test_original_state_not_mutated(self):
        base = state(make_listener(80))
        opened = Change(kind="open", ts=1.0, listener=make_listener(8080))
        apply_changes(base, [opened])
        assert len(base) == 1
