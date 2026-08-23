from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

from port_authority.model import Change

ENV_PREFIX = "PORT_AUTHORITY"


def events_to_json(changes: list[Change]) -> str:
    return json.dumps(
        [
            {
                "kind": c.kind,
                "ts": c.ts,
                "proto": c.listener.proto,
                "port": c.listener.port,
                "address": c.listener.address,
                "pid": c.listener.pid,
                "process": c.listener.process,
            }
            for c in changes
        ]
    )


@dataclass
class HookResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0


def run_hook(command: str, changes: list[Change], timeout: float = 30.0) -> Optional[HookResult]:
    """Run the --on-change command with event context in the environment.

    Never raises: failures are captured in the returned result so the watch
    loop cannot be interrupted by a broken hook.
    """
    if not command or not changes:
        return None
    env = {**os.environ, f"{ENV_PREFIX}_EVENTS": events_to_json(changes)}
    try:
        proc = subprocess.run(
            command,
            shell=True,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return HookResult(command=command, returncode=-1, error=f"timed out after {timeout:g}s")
    except OSError as exc:
        return HookResult(command=command, returncode=-1, error=str(exc))
    return HookResult(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
