from __future__ import annotations

import json

from port_authority.alerts import HookResult, events_to_json, run_hook
from port_authority.model import Change, make_listener


def changes():
    return [
        Change(kind="open", ts=1.0, listener=make_listener(8080)),
        Change(kind="close", ts=2.0, listener=make_listener(53, proto="udp")),
    ]


class TestEventsToJson:
    def test_shape(self):
        data = json.loads(events_to_json(changes()))
        assert [d["kind"] for d in data] == ["open", "close"]
        assert data[0]["process"] == "nginx"
        assert "ts" in data[0] and "port" in data[0]


class TestRunHook:
    def test_success_and_env(self):
        result = run_hook("true", changes())
        assert isinstance(result, HookResult)
        assert result.ok and result.returncode == 0

    def test_env_contains_events(self):
        result = run_hook('printf "%s" "$PORT_AUTHORITY_EVENTS" | grep -q 8080', changes())
        assert result.ok

    def test_nonzero_exit_captured(self):
        result = run_hook("exit 3", changes())
        assert not result.ok and result.returncode == 3

    def test_timeout_captured(self):
        result = run_hook("sleep 5", changes(), timeout=0.2)
        assert not result.ok and "timed out" in result.error

    def test_empty_command_or_changes(self):
        assert run_hook("", changes()) is None
        assert run_hook("true", []) is None
