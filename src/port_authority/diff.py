from __future__ import annotations

from port_authority.model import Change, Listener, ListenerKey

State = dict[ListenerKey, Listener]


def diff_state(prev: State, curr: State) -> list[Change]:
    """Transitions between two listener states, ordered by port."""
    changes: list[Change] = []
    for key, listener in curr.items():
        if key not in prev:
            changes.append(Change(kind="open", ts=0.0, listener=listener))
    for key, listener in prev.items():
        if key not in curr:
            changes.append(Change(kind="close", ts=0.0, listener=listener))
    changes.sort(key=lambda c: (c.listener.port, c.kind))
    return changes


def apply_changes(state: State, changes: list[Change]) -> State:
    """Pure state transition; returns a new dict."""
    nxt = dict(state)
    for change in changes:
        key = change.listener.key()
        if change.kind == "open":
            nxt[key] = change.listener
        else:
            nxt.pop(key, None)
    return nxt
