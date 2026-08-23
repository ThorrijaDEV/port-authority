from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Listener:
    pid: int | None
    process: str | None
    proto: str
    port: int
    address: str
    started_at: float | None = None

    def key(self) -> "ListenerKey":
        return ListenerKey(self.proto, self.port, self.address)


@dataclass(frozen=True)
class ListenerKey:
    proto: str
    port: int
    address: str

    def as_tuple(self) -> tuple[str, int, str]:
        return (self.proto, self.port, self.address)


@dataclass(frozen=True)
class Change:
    kind: str  # "open" | "close"
    ts: float
    listener: Listener

    @property
    def port(self) -> int:
        return self.listener.port

    def with_ts(self, ts: float) -> "Change":
        return replace(self, ts=ts)


def make_listener(
    port: int,
    pid: int = 100,
    process: str | None = "nginx",
    proto: str = "tcp",
    address: str = "0.0.0.0",
    started_at: float | None = 1_000_000.0,
) -> Listener:
    return Listener(pid=pid, process=process, proto=proto, port=port, address=address, started_at=started_at)
