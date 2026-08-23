from __future__ import annotations

import json
import time

import pytest

import port_authority.cli as cli
from port_authority.model import Change, make_listener


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "history.db"


def seed(store, events):
    for ts, kind, port in events:
        store.record_changes([Change(kind=kind, ts=ts, listener=make_listener(port=port))], ts)


class TestScan:
    def test_json_output(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "scan", lambda include_udp: [make_listener(8080)])
        rc = cli.main(["scan", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out[0]["port"] == 8080

    def test_table_output(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "scan", lambda include_udp: [make_listener(80)])
        rc = cli.main(["scan"])
        text = capsys.readouterr().out
        assert rc == 0
        assert "PROTO" in text and "80" in text


class TestLogAndDiff:
    def test_log_filters(self, db, monkeypatch, capsys):
        store = cli.Store(db)
        seed(store, [(1.0, "open", 80), (2.0, "open", 443), (3.0, "close", 80)])
        store.close()

        rc = cli.main(["--db", str(db), "log", "--kind", "close"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "- close" in out and "80" in out
        assert "443" not in out

    def test_log_empty(self, db, capsys):
        rc = cli.main(["--db", str(db), "log"])
        assert rc == 0
        assert "No events" in capsys.readouterr().out

    def test_diff_between_restarts(self, db, capsys):
        now = time.time()
        store = cli.Store(db)
        seed(store, [
            (now - 3600 * 3, "open", 3000),
            (now - 3600 * 2, "close", 3000),
            (now - 60, "open", 9000),
        ])
        store.close()
        rc = cli.main(["--db", str(db), "diff", "--since", "1h"])
        out = capsys.readouterr().out
        assert rc == 0
        # Only the recent open is inside the window: 3000 closed before it started.
        assert "9000" in out and "3000" not in out

    def test_diff_json(self, db, monkeypatch, capsys):
        store = cli.Store(db)
        seed(store, [(time.time() - 60, "open", 5000)])
        store.close()
        rc = cli.main(["--db", str(db), "diff", "--since", "1h", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert len(data) == 1 and data[0]["port"] == 5000


class TestReport:
    def test_text_report(self, db, capsys):
        t = time.time()
        store = cli.Store(db)
        seed(store, [(t - 10, "open", 8000), (t - 5, "close", 8000)])
        store.close()
        rc = cli.main(["--db", str(db), "report", "--since", "1h"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "1 opened" in out and "1 closed" in out and "8000 (2x)" in out

    def test_json_report(self, db, capsys):
        t = time.time()
        store = cli.Store(db)
        seed(store, [(t - 10, "open", 8000)])
        store.close()
        rc = cli.main(["--db", str(db), "report", "--since", "1h", "--format", "json"])
        data = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert data["opened"] == 1 and data["by_port"]["8000"]["opened"] == 1


class TestValidation:
    def test_bad_duration(self):
        with pytest.raises(SystemExit):
            cli.main(["log", "--since", "yesterday??"])

    @pytest.mark.parametrize("value,expected", [
        ("30s", 30.0), ("10m", 600.0), ("2h", 7200.0), ("7d", 604800.0),
    ])
    def test_parse_duration(self, value, expected):
        from port_authority.format import parse_duration

        assert parse_duration(value) == expected


class TestWatch:
    def test_watch_records_and_runs_hook(self, db, monkeypatch, tmp_path):
        marker = tmp_path / "hook.txt"
        scans = iter([[make_listener(7000)], [make_listener(7000), make_listener(7001)]])
        monkeypatch.setattr(cli, "scan", lambda include_udp: next(scans))
        sleeps = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        def stop_after_two_cycles():
            if len(sleeps) >= 2:
                raise KeyboardInterrupt

        real_sleep = time.sleep
        monkeypatch.setattr(cli.time, "sleep", lambda s: (real_sleep(0), stop_after_two_cycles()))

        hook_cmd = f'echo "$PORT_AUTHORITY_EVENTS" >> {marker}'
        rc = cli.main(["--db", str(db), "watch", "-i", "0.1", "--on-change", hook_cmd])
        out_err = None
        assert rc == 0
        assert marker.exists(), "hook never ran"
        lines = marker.read_text().strip().splitlines()
        assert len(lines) == 1, f"expected one change batch, got {lines}"
        batch = json.loads(lines[0])
        assert batch[0] == {
            **batch[0],
            "kind": "open", "port": 7000,
        }
