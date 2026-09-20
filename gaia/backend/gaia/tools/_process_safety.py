"""Shared subprocess-safety helpers for tools that execute code or commands in
an isolated subprocess (`python_sandbox.py`, `terminal.py`). Not a tool
itself — no `Tool` subclass lives here, just the plumbing both share.
"""

from __future__ import annotations

import os
from collections.abc import Callable


def posix_resource_limits(
    *, memory_bytes: int, cpu_seconds: int, max_processes: int = 16
) -> Callable[[], None]:
    """Build a zero-arg callable for `subprocess.Popen(preexec_fn=...)`.

    Runs in the child after `fork()` and before `exec()` — the only point
    from pure Python these limits can be applied to a subprocess. POSIX
    only: `resource` does not exist on Windows, so the returned callable
    must never be referenced there; callers gate this behind
    `os.name == "posix"` and must not call this factory itself on Windows.
    """

    def _apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
        except (ValueError, OSError):
            pass  # not available on every POSIX platform (e.g. restricted on macOS)

    return _apply


def minimal_environment(allowlist: tuple[str, ...]) -> dict[str, str]:
    """A sanitised environment containing only allow-listed variables.

    The backend process may hold API keys in its own environment (see
    `core/secrets.py`). Never hand those to a child process — pass only
    what the caller explicitly allow-lists.
    """
    upper_allowlist = {key.upper() for key in allowlist}
    return {key: value for key, value in os.environ.items() if key.upper() in upper_allowlist}


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text) - limit} more characters]"
