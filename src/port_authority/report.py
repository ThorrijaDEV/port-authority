from __future__ import annotations

import json
import re
from collections import Counter
from typing import Iterable, Optional

from port_authority.format import Style, fmt_ts
from port_authority.model import Change, Listener

LISTENER_HEADERS = ("PROTO", "PORT", "ADDRESS", "PID", "PROCESS")


def render_listeners(listeners: list[Listener], style: Style) -> str:
    rows = [
        (l.proto, str(l.port), l.address, "-" if l.pid is None else str(l.pid), l.process or "(unknown)")
        for l in listeners
    ]
    return _table(LISTENER_HEADERS, rows, style)


def render_changes(changes: list[Change], style: Style, with_ts: bool = True) -> str:
    headers = ["TIME", "EVENT", "PROTO", "PORT", "ADDRESS", "PID", "PROCESS"]
    rows = []
    for c in changes:
        kind = style.good("+ open") if c.kind == "open" else style.bad("- close")
        rows.append(
            (
                fmt_ts(c.ts),
                kind,
                c.listener.proto,
                str(c.listener.port),
                c.listener.address,
                "-" if c.listener.pid is None else str(c.listener.pid),
                c.listener.process or "(unknown)",
            )
        )
    if not with_ts:
        headers = headers[1:]
        rows = [r[1:] for r in rows]
    if not rows:
        return style.dim("No changes recorded.")
    return _table(headers, rows, style)


def render_report(
    events: list[Change],
    since_label: str,
    style: Style,
) -> str:
    lines: list[str] = []
    opens = [e for e in events if e.kind == "open"]
    closes = [e for e in events if e.kind == "close"]
    lines.append(style.bold(f"Port Authority report — {since_label}"))
    lines.append(f"Events: {len(events)} ({len(opens)} opened, {len(closes)} closed)")
    if not events:
        lines.append("Nothing happened in this period.")
        return "\n".join(lines)

    by_port = Counter(e.listener.port for e in events)
    top = ", ".join(f"{port} ({n}x)" for port, n in by_port.most_common(5))
    lines.append(f"Busiest ports: {top}")

    processes = Counter(
        e.listener.process or "(unknown)" for e in events if e.kind == "open"
    )
    procs = ", ".join(f"{name} ({n})" for name, n in processes.most_common(5))
    lines.append(f"Processes that opened ports: {procs}")

    lines.append("")
    lines.append(render_changes(events, style))
    return "\n".join(lines)


def to_json_list(changes: Iterable[Change]) -> str:
    return json.dumps([_change_dict(c) for c in changes], indent=2)


def _change_dict(c: Change) -> dict:
    return {
        "ts": c.ts,
        "iso": fmt_ts(c.ts),
        "kind": c.kind,
        "proto": c.listener.proto,
        "port": c.listener.port,
        "address": c.listener.address,
        "pid": c.listener.pid,
        "process": c.listener.process,
    }


def _table(headers: tuple[str, ...] | list[str], rows: list[tuple[str, ...]], style: Style,
           widths: Optional[list[int]] = None) -> str:
    if widths is None:
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                # ANSI codes would inflate len(); strip before measuring.
                plain_len = len(_strip_ansi(cell))
                widths[i] = max(widths[i], plain_len)

    def fmt_row(cells: Iterable[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            pad = widths[i] - len(_strip_ansi(cell))
            parts.append(cell + " " * pad)
        return "  ".join(parts).rstrip()

    out = [style.bold(fmt_row(headers)), style.dim("  ".join("-" * w for w in widths))]
    out.extend(fmt_row(r) for r in rows)
    return "\n".join(out)


_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)
