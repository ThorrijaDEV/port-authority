from __future__ import annotations

import pytest

from port_authority.format import Style, fmt_ts, parse_since


class TestParseSince:
    def test_duration(self):
        now = 1_000_000.0
        assert parse_since("24h", now) == pytest.approx(now - 86400)

    def test_iso_date(self):
        ts = parse_since("2026-08-01", 0)
        assert ts == __import__("datetime").datetime(2026, 8, 1).timestamp()

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="invalid --since"):
            parse_since("not a date or duration", 0)


def test_fmt_ts_format():
    assert fmt_ts(0) != "" and len(fmt_ts(0)) == 19


def test_style_disabled_when_not_tty(capsys):
    style = Style(enabled=True)
    assert style.bold("x") == "x"  # capsys stdout is not a tty
