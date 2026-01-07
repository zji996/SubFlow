"""Async-friendly subprocess helpers.

We prefer `subprocess.run()` executed via `asyncio.to_thread()` instead of
`asyncio.create_subprocess_exec()` since some runtime environments have flaky
child watchers that can cause `.wait()`/`.communicate()` to hang.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


async def run_subprocess(
    args: Sequence[str],
    *,
    capture_output: bool = True,
    check: bool = False,
    timeout_s: float | None = None,
) -> RunResult:
    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            list(args),
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            check=check,
            timeout=timeout_s,
        )

    cp = await asyncio.to_thread(_run)
    return RunResult(
        returncode=int(cp.returncode),
        stdout=cp.stdout or b"",
        stderr=cp.stderr or b"",
    )
