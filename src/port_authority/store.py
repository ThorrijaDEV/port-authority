from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from port_authority.model import Change, Listener, ListenerKey

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('open', 'close')),
    proto TEXT NOT NULL,
    port INTEGER NOT NULL,
    address TEXT NOT NULL,
    pid INTEGER,
    process TEXT,
    proc_started REAL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_port ON events(port);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass

    def close(self) -> None:
        self.conn.close()

    # -- writes ---------------------------------------------------------------

    def record_changes(self, changes: list[Change], ts: float) -> int:
        rows = [
            (
                change.ts or ts,
                change.kind,
                change.listener.proto,
                change.listener.port,
                change.listener.address,
                change.listener.pid,
                change.listener.process,
                change.listener.started_at,
            )
            for change in changes
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO events (ts, kind, proto, port, address, pid, process, proc_started)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            if changes:
                self.set_meta("last_change_ts", repr(rows[-1][0]))
        return len(rows)

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # -- reads ----------------------------------------------------------------

    def iter_events(
        self,
        since: Optional[float] = None,
        until: Optional[float] = None,
        port: Optional[int] = None,
        kind: Optional[str] = None,
        reverse: bool = False,
    ) -> Iterator[Change]:
        query = "SELECT * FROM events WHERE 1=1"
        params: list[object] = []
        if since is not None:
            query += " AND ts >= ?"
            params.append(since)
        if until is not None:
            query += " AND ts <= ?"
            params.append(until)
        if port is not None:
            query += " AND port = ?"
            params.append(port)
        if kind in ("open", "close"):
            query += " AND kind = ?"
            params.append(kind)
        query += " ORDER BY ts DESC, id DESC" if reverse else " ORDER BY ts ASC, id ASC"
        for row in self.conn.execute(query, params):
            yield _row_to_change(row)

    def replay_state(self, until: Optional[float] = None) -> dict[ListenerKey, Listener]:
        """Rebuild the listener state by applying the whole event stream."""
        state: dict[ListenerKey, Listener] = {}
        for change in self.iter_events(until=until):
            key = change.listener.key()
            if change.kind == "open":
                state[key] = change.listener
            else:
                state.pop(key, None)
        return state

    def count_events(self, since: Optional[float] = None) -> int:
        query = "SELECT COUNT(*) AS n FROM events"
        params: list[object] = []
        if since is not None:
            query += " WHERE ts >= ?"
            params.append(since)
        row = self.conn.execute(query, params).fetchone()
        return int(row["n"])


def _row_to_change(row: sqlite3.Row) -> Change:
    listener = Listener(
        pid=row["pid"],
        process=row["process"],
        proto=row["proto"],
        port=row["port"],
        address=row["address"],
        started_at=row["proc_started"],
    )
    return Change(kind=row["kind"], ts=row["ts"], listener=listener)
