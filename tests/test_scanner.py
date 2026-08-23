from __future__ import annotations

import socket
import types

import psutil
import pytest

from port_authority.model import Listener, make_listener
from port_authority.scanner import ProcessInfo, scan, to_listener


@pytest.fixture()
def no_proc_lookup(monkeypatch):
    """Keep tests hermetic: never touch /proc for names."""
    monkeypatch.setattr(
        "port_authority.scanner._process_info",
        lambda pid: ProcessInfo(name=f"proc{pid}", started_at=42.0),
    )


def fake_conn(pid=100, family=socket.AF_INET, type_=socket.SOCK_STREAM,
              laddr=("0.0.0.0", 80), status=psutil.CONN_LISTEN):
    return types.SimpleNamespace(
        pid=pid, family=family, type=type_, laddr=laddr, raddr=(), status=status,
    )


class TestToListener:
    def test_tcp_listener(self, no_proc_lookup):
        listener = to_listener(fake_conn())
        assert listener == Listener(
            pid=100, process="proc100", proto="tcp", port=80,
            address="0.0.0.0", started_at=42.0,
        )

    def test_unknown_pid_keeps_none_metadata(self):
        # pid None (not ours / kernel) or 0: no metadata is available.
        for pid in (None, 0):
            listener = to_listener(fake_conn(pid=pid))
            assert listener.pid == pid
            assert listener.process is None
            assert listener.started_at is None

    def test_established_connection_ignored(self):
        conn = fake_conn(status=psutil.CONN_ESTABLISHED, laddr=("10.0.0.2", 52100))
        assert to_listener(conn) is None

    def test_udp_bound_socket_counts(self, no_proc_lookup):
        conn = fake_conn(type_=socket.SOCK_DGRAM, laddr=("0.0.0.0", 53))
        listener = to_listener(conn)
        assert listener.proto == "udp"
        assert listener.port == 53

    def test_udp_unbound_ignored(self):
        conn = fake_conn(type_=socket.SOCK_DGRAM, laddr=())
        assert to_listener(conn) is None

    def test_ipv6(self, no_proc_lookup):
        tcp6 = to_listener(fake_conn(family=socket.AF_INET6, laddr=("::", 22)))
        udp6 = to_listener(fake_conn(family=socket.AF_INET6, type_=socket.SOCK_DGRAM, laddr=("::", 53)))
        assert tcp6.proto == "tcp6"
        assert udp6.proto == "udp6"


class TestScan:
    def test_deduplicates_and_sorts(self, monkeypatch, no_proc_lookup):
        conns = [
            fake_conn(laddr=("0.0.0.0", 443), pid=101),
            fake_conn(laddr=("0.0.0.0", 80), pid=100),
            fake_conn(laddr=("127.0.0.1", 8080), pid=102),
            # duplicate entry for the same socket
            fake_conn(laddr=("0.0.0.0", 80), pid=100),
            # established noise
            fake_conn(status=psutil.CONN_ESTABLISHED, laddr=("10.0.0.2", 52100)),
        ]
        monkeypatch.setattr(psutil, "net_connections", lambda kind: conns)
        listeners = scan()
        ports = [l.port for l in listeners]
        assert ports == [80, 443, 8080]

    def test_udp_excluded_by_default(self, monkeypatch, no_proc_lookup):
        conns = [
            fake_conn(laddr=("0.0.0.0", 80)),
            fake_conn(type_=socket.SOCK_DGRAM, laddr=("0.0.0.0", 53), pid=7),
        ]
        monkeypatch.setattr(psutil, "net_connections", lambda kind: conns)
        assert [l.port for l in scan()] == [80]
        assert [l.port for l in scan(include_udp=True)] == [53, 80]
