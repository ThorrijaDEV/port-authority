# Port Authority

A historian for Linux network ports: **who listened where, when, for how long.**

`ss`, `lsof` and `netstat` answer *"what is listening right now?"* — and nothing else. The moment a process exits, the evidence is gone. Port Authority keeps that evidence: it records every port open/close event into a local SQLite database so you can go back and ask what happened while you weren't looking.

```
$ port-authority log --since 24h
TIME                 EVENT    PROTO  PORT  ADDRESS     PID   PROCESS
2026-08-23 03:12:44  - close  tcp    8080  0.0.0.0     9143  gunicorn
2026-08-23 03:13:02  + open   tcp    8081  127.0.0.1   9922  python
```

## Why

Typical questions this tool answers:

- Something was serving on port 5000 last night. What process was it?
- Did anything new start listening since yesterday? On which address?
- Which ports did this binary open and close over the last week?

It is small on purpose: one binary, one dependency (`psutil`), no daemons to configure, no network calls. Everything stays in `~/.local/state/port-authority/`.

## Features

- **Event history** — every listener transition (open/close) is timestamped in SQLite (WAL mode).
- **Restart-proof diffs** — state is reconstructed by replaying the event log, so a close that happened while `watch` wasn't running is still detected on the next scan.
- **Queries** — filter events by period (`--since 24h`, `--since 2026-08-01`), port, kind, or any combination.
- **Point-in-time diff** — compare the listener state between two arbitrary moments.
- **Reports** — text or JSON summaries of a period: totals, busiest ports, processes involved.
- **Hooks** — `--on-change CMD` runs your command on every change batch with `$PORT_AUTHORITY_EVENTS` (JSON) in the environment.
- **UDP opt-in** — TCP listeners are tracked by default; bound UDP sockets can be included with `--udp`.
- **Honest colors** — ANSI output only when stdout/stderr is a TTY.

## Installation

Requires Python ≥ 3.9 on Linux.

```bash
git clone https://github.com/ThorrijaDEV/port-authority
cd port-authority
python3 -m venv .venv && source .venv/bin/activate
pip install .
port-authority --help
```

Or with [pipx](https://pipx.pypa.io/) / [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/ThorrijaDEV/port-authority
```

## Usage

### One-shot snapshot

```bash
port-authority scan            # table of current listeners
port-authority scan --udp      # include bound UDP sockets
port-authority scan --json     # machine readable
```

### Continuous recording

```bash
# Record changes every 5s into the default database
port-authority watch

# Faster polling + desktop notification hook
port-authority watch -i 2 --on-change 'notify-send "Port change" "$PORT_AUTHORITY_EVENTS"'
```

`watch` prints each batch of transitions as they happen (to stderr) and stores them (to SQLite). It stops cleanly on Ctrl-C.

### Querying history

```bash
port-authority log --since 24h                    # everything from the last day
port-authority log --since 7d --kind open         # only opens
port-authority log --port 8080 --since 48h        # full story of one port
port-authority log --until 2026-08-20 --json      # JSON output
```

### Diff between two moments

```bash
port-authority diff --since 1h                    # what changed in the last hour
port-authority diff --since 2026-08-01 --until 2026-08-15
```

The diff replays recorded events, so both endpoints may fall in periods where `watch` wasn't running — you get the net transitions between those points.

### Reports

```bash
port-authority report --since 7d
port-authority report --since 30d --format json | jq .
```

Example:

```
Port Authority report — 7d
Events: 42 (31 opened, 11 closed)
Busiest ports: 8080 (12x), 5432 (8x), 47615 (6x)
Processes that opened ports: python (18), docker-proxy (9), postgres (4)
```

## Configuration

| Setting | Default |
|---|---|
| Database path | `$XDG_STATE_HOME/port-authority/history.db` (`~/.local/state/...`) |
| Override | `PORT_AUTHORITY_DB=/path/to.db` env var, or global `--db PATH` flag |

No config files. The schema is created automatically on first use; delete the file to start fresh.

## How it works

```
psutil.net_connections()          SQLite event log            CLI
┌──────────────────────┐  scan   ┌─────────────────┐  query   ┌──────────┐
│ listeners (pid, port,│ ──────▶ │ events(ts, kind,│ ◀─────── │ log/diff │
│ proto, addr, status) │  diff   │  proto, port…)  │  replay  │ report   │
└──────────────────────┘         └─────────────────┘          └──────────┘
```

- A **listener identity** is `(proto, port, address)` — metadata such as pid/process changing does not count as an event; the socket binding/unbinding does.
- `diff` rebuilds past states from the log (`replay_state`), which makes restarts and gaps invisible to queries.
- Hooks run through the shell with a 30s timeout; failures are reported but never stop the watch loop.

## Limitations

- Linux only (uses `psutil.net_connections`, which reads `/proc/net/*`).
- Processes that exit immediately after binding may appear as `(unknown)` if `/proc/<pid>` is gone before the next poll.
- Poll-based: very short-lived bindings between polls are missed. Lower `--interval` reduces the window.
- UDP tracking is off by default because *bound* ≠ *serving* for datagram sockets; enable it when you want the full picture.
- No privilege escalation: without root you will see pids only for sockets owned by your user (same visibility as `ss -tlnp` unprivileged).

## Development

```bash
git clone https://github.com/ThorrijaDEV/port-authority
cd port-authority
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest
pytest
```

Project layout:

```
src/port_authority/
├── model.py     # Listener / Change dataclasses (pure)
├── scanner.py   # psutil → normalized listeners
├── diff.py      # pure state-transition logic
├── store.py     # SQLite event log + replay
├── alerts.py    # --on-change hooks
├── format.py    # durations, timestamps, ANSI style
└── cli.py       # argparse wiring
tests/           # unit tests, no root required
```

Tests run fully offline with fake connection objects — they never touch real sockets or require privileges.

## Roadmap

- [ ] `state-at <timestamp>` command: exact listener table at a past moment
- [ ] Optional systemd unit for always-on recording
- [ ] Export to Prometheus text format
- [ ] Process tree context at event time (parent command line)

## License

[MIT](LICENSE)
