from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

from port_authority import report as fmt
from port_authority.alerts import run_hook
from port_authority.diff import diff_state, apply_changes
from port_authority.format import Style, parse_since
from port_authority.model import Change
from port_authority.scanner import scan
from port_authority.store import Store

DEFAULT_DB = Path(
    os.environ.get("PORT_AUTHORITY_DB")
    or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    / "port-authority"
    / "history.db"
)
DEFAULT_INTERVAL = 5.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="port-authority",
        description="A historian for Linux network ports: who listened where, when.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite history file (default: %(default)s)")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="print the current listening sockets")
    p_scan.add_argument("--udp", action="store_true", help="include bound UDP sockets")
    p_scan.add_argument("--json", action="store_true", dest="as_json", help="output JSON")

    p_watch = sub.add_parser("watch", help="record port events continuously")
    p_watch.add_argument("-i", "--interval", type=float, default=DEFAULT_INTERVAL, metavar="SEC")
    p_watch.add_argument("--udp", action="store_true", help="include bound UDP sockets")
    p_watch.add_argument("--on-change", metavar="CMD", help="shell command run on every change batch")

    p_log = sub.add_parser("log", help="query recorded events")
    p_log.add_argument("--since", metavar="DUR|ISO", help="e.g. 24h or 2026-08-01")
    p_log.add_argument("--until", metavar="DUR|ISO", help="defaults to now (durations count back from now)")
    p_log.add_argument("--port", type=int)
    p_log.add_argument("--kind", choices=("open", "close"))
    p_log.add_argument("--json", action="store_true", dest="as_json")

    p_diff = sub.add_parser("diff", help="listener state changes between two points in time")
    p_diff.add_argument("--since", metavar="DUR|ISO", default="1h", help="start point (default: 1h)")
    p_diff.add_argument("--until", metavar="DUR|ISO", help="end point (default: now)")
    p_diff.add_argument("--json", action="store_true", dest="as_json")

    p_report = sub.add_parser("report", help="summarize a period")
    p_report.add_argument("--since", metavar="DUR|ISO", default="24h")
    p_report.add_argument("--format", choices=("text", "json"), default="text", dest="fmt")

    return parser


def cmd_scan(args: argparse.Namespace, store: Optional[Store], style: Style) -> int:
    listeners = scan(include_udp=args.udp)
    if args.as_json:
        print(json.dumps([_listener_dict(l) for l in listeners], indent=2))
        return 0
    if not listeners:
        print(style.dim("Nothing is listening."))
        return 0
    print(fmt.render_listeners(listeners, style))
    return 0


def cmd_watch(args: argparse.Namespace, store: Store, style: Style) -> int:
    interval = max(0.5, args.interval)
    state = store.replay_state()
    current_ts = time.time()

    def stop(signum, frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    print(
        style.dim(
            f"Watching every {interval:g}s — {len(state)} known listener(s). Ctrl-C to stop."
        ),
        file=sys.stderr,
    )
    try:
        while True:
            time.sleep(interval)
            now = time.time()
            try:
                current = scan(include_udp=args.udp)
            except OSError as exc:
                print(style.bad(f"scan failed: {exc}"), file=sys.stderr)
                continue
            changes = [c.with_ts(now) for c in diff_state(state, {(l.key()): l for l in current})]
            state = apply_changes(state, changes)
            if not changes:
                continue
            store.record_changes(changes, now)
            print(fmt.render_changes(changes, style), file=sys.stderr)
            hook = run_hook(args.on_change, changes) if args.on_change else None
            if hook and not hook.ok:
                detail = hook.error or f"exit {hook.returncode}: {hook.stderr.strip()}"
                print(style.bad(f"on-change hook failed: {detail}"), file=sys.stderr)
    except KeyboardInterrupt:
        print(style.dim("Stopped."), file=sys.stderr)
    return 0


def _range(args: argparse.Namespace) -> tuple[float, float]:
    now = time.time()
    since = parse_since(args.since, now)
    until = parse_since(getattr(args, "until", None), now)
    return since or 0.0, until if until is not None else now


def cmd_log(args: argparse.Namespace, store: Store, style: Style) -> int:
    since, until = _range(args)
    events = list(
        store.iter_events(since=since, until=until, port=args.port, kind=args.kind, reverse=True)
    )
    if args.as_json:
        print(fmt.to_json_list(events))
        return 0
    if not events:
        print(style.dim("No events in this period."))
        return 0
    print(fmt.render_changes(events, style))
    return 0


def cmd_diff(args: argparse.Namespace, store: Store, style: Style) -> int:
    start, end = _range(args)
    before = store.replay_state(until=start)
    after = store.replay_state(until=end)
    changes = [
        c.with_ts(end) for c in diff_state(before, after)
    ]
    if args.as_json:
        print(fmt.to_json_list(changes))
        return 0
    label = f"{args.since} → {'now' if getattr(args, 'until', None) is None else args.until}"
    header = style.bold(f"Changes between {label}:")
    body = fmt.render_changes(changes, style)
    print(f"{header}\n{body}")
    return 0


def cmd_report(args: argparse.Namespace, store: Store, style: Style) -> int:
    since, until = _range(args)
    events = list(store.iter_events(since=since, until=until))
    if args.fmt == "json":
        opens = sum(1 for e in events if e.kind == "open")
        closes = len(events) - opens
        ports = {}
        for e in events:
            entry = ports.setdefault(e.listener.port, {"opened": 0, "closed": 0})
            entry["opened" if e.kind == "open" else "closed"] += 1
        print(json.dumps({"since": args.since, "events": len(events),
                          "opened": opens, "closed": closes,
                          "by_port": dict(sorted(ports.items()))}, indent=2))
        return 0
    print(fmt.render_report(events, args.since, style))
    return 0


def _listener_dict(l) -> dict:
    return {
        "proto": l.proto,
        "port": l.port,
        "address": l.address,
        "pid": l.pid,
        "process": l.process,
    }


COMMANDS = {
    "scan": cmd_scan,
    "watch": cmd_watch,
    "log": cmd_log,
    "diff": cmd_diff,
    "report": cmd_report,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    style = Style(enabled=not args.no_color)

    needs_store = args.command != "scan"
    store = Store(args.db) if needs_store else None
    try:
        return COMMANDS[args.command](args, store, style)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
