from __future__ import annotations

import socket

import psutil

from port_authority.model import Listener, ListenerKey

TCP_LISTEN = psutil.CONN_LISTEN
_IPV6 = socket.AF_INET6


class ProcessInfo:
    __slots__ = ("name", "started_at")

    def __init__(self, name: str | None, started_at: float | None):
        self.name = name
        self.started_at = started_at


def _process_info(pid: int | None) -> ProcessInfo:
    if not pid or pid <= 0:
        return ProcessInfo(None, None)
    try:
        proc = psutil.Process(pid)
        return ProcessInfo(proc.name(), proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ProcessInfo(None, None)


def to_listener(conn) -> Listener | None:
    """Normalize one psutil connection entry; returns None for non-listeners."""
    if conn.type == socket.SOCK_STREAM:
        if conn.status != TCP_LISTEN:
            return None
        proto = "tcp6" if conn.family == _IPV6 else "tcp"
        address, port = conn.laddr
    else:
        # UDP sockets have no listen state: any bound socket counts.
        proto = "udp6" if conn.family == _IPV6 else "udp"
        if not conn.laddr:
            return None
        address, port = conn.laddr
    info = _process_info(conn.pid)
    return Listener(
        pid=conn.pid,
        process=info.name,
        proto=proto,
        port=int(port),
        address=str(address),
        started_at=info.started_at,
    )


def scan(include_udp: bool = False) -> list[Listener]:
    """Snapshot of current listening sockets, sorted for stable diffs."""
    seen: dict[ListenerKey, Listener] = {}
    for conn in psutil.net_connections(kind="inet"):
        listener = to_listener(conn)
        if listener is None:
            continue
        if listener.proto.startswith("udp") and not include_udp:
            continue
        key = listener.key()
        if key not in seen:
            seen[key] = listener
    return sorted(seen.values(), key=lambda l: (l.port, l.proto, l.address))
