from __future__ import annotations

import re
import sys
from datetime import datetime
from typing import Optional

UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$", re.IGNORECASE)


def parse_duration(text: str) -> float:
    """'30s' | '10m' | '2h' | '7d' | '1w' -> seconds. Raises ValueError otherwise."""
    match = DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration: {text!r} (expected e.g. 30s, 10m, 2h, 7d)")
    return float(match.group(1)) * UNIT_SECONDS[match.group(2).lower()]


def parse_since(text: Optional[str], now: float) -> Optional[float]:
    """Accepts a duration ('24h') or an ISO date ('2026-08-01')."""
    if text is None:
        return None
    if DURATION_RE.match(text):
        return now - parse_duration(text)
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(f"{text}T00:00").timestamp()
    except ValueError:
        raise ValueError(f"invalid --since value: {text!r} (use a duration like 24h or an ISO date)")


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled and sys.stdout.isatty()

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def good(self, text: str) -> str:
        return self._wrap("32", text)

    def bad(self, text: str) -> str:
        return self._wrap("31", text)
