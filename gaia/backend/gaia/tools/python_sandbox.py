"""Python sandbox — a CONFIRM-risk tool. Executes code in an isolated subprocess.

This is a meaningfully different risk class from `calculator.py`: that tool
evaluates a closed arithmetic grammar and cannot escape it by construction.
This one runs arbitrary Python. What *is* enforced:

- A separate subprocess (never inline in the API process — see docs/SECURITY.md).
- A wall-clock timeout, after which the process is killed.
- `-I` (isolated mode): ignores the parent's `PYTHON*` environment variables
  and the user site-packages directory.
- A sanitised environment: the child never sees GAIA's own environment (which
  may hold API keys — see `core/secrets.py`), only what the interpreter needs
  to start.
- A dedicated working directory (`config.sandbox_dir`), so file output (e.g.
  a saved plot) lands somewhere contained rather than wherever the backend
  process happens to be running.
- Memory/CPU/process-count limits via `resource.setrlimit`, **POSIX only** —
  there is no equivalent stdlib mechanism on Windows. On Windows this tool
  has no enforced memory or CPU ceiling beyond the wall-clock timeout.

What is **not** enforced, disclosed rather than hidden:

- No network isolation. Sandboxed code can make outbound connections.
- No import-level containment. The subprocess uses the same interpreter and
  `site-packages` as the backend itself, so `import gaia` succeeds and can
  reach the app's own database and secrets modules. Real containment needs a
  separate restricted interpreter or OS-level sandboxing (a container, a VM,
  Windows Sandbox) — out of scope for this first pass.

Because of the above, this tool is `RiskLevel.CONFIRM`: the human-in-the-loop
approval is real protection today even where the technical sandboxing is
partial.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

from gaia.config import get_settings
from gaia.tools._process_safety import minimal_environment, posix_resource_limits, truncate
from gaia.tools.base import RiskLevel, Tool, ToolResult

MAX_CODE_LENGTH = 20_000
TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 20_000
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024  # 256 MB — POSIX only
CPU_TIME_LIMIT_SECONDS = 10  # POSIX only

# Environment variables the child process is allowed to see. Nothing GAIA-
# specific (no ANTHROPIC_API_KEY, no GAIA_DATA_DIR override, ...) — just what
# the interpreter itself needs to start and locate a temp directory.
_ENV_ALLOWLIST = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")


class PythonSandboxTool(Tool):
    name = "python_sandbox"
    description = (
        "Execute Python code in an isolated subprocess for calculations, data "
        "analysis, or algorithm exploration that the calculator tool cannot "
        "express. Runs with a wall-clock timeout and a dedicated working "
        "directory. Only stdout is returned — print() whatever you want back. "
        "Prefer the calculator tool for plain arithmetic."
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python source to execute. Use print() for any output "
                "you want returned.",
            }
        },
        "required": ["code"],
    }
    risk_level = RiskLevel.CONFIRM

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        code = arguments.get("code")
        if not isinstance(code, str) or not code.strip():
            return ToolResult(ok=False, content="", error="'code' must be a non-empty string")
        if len(code) > MAX_CODE_LENGTH:
            return ToolResult(
                ok=False,
                content="",
                error=f"code too long (limit {MAX_CODE_LENGTH} characters)",
            )

        settings = get_settings()
        settings.ensure_directories()

        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            popen_kwargs["preexec_fn"] = posix_resource_limits(
                memory_bytes=MEMORY_LIMIT_BYTES, cpu_seconds=CPU_TIME_LIMIT_SECONDS
            )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-"],
                input=code,
                capture_output=True,
                text=True,
                cwd=str(settings.sandbox_dir),
                env=minimal_environment(_ENV_ALLOWLIST),
                timeout=TIMEOUT_SECONDS,
                **popen_kwargs,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False, content="", error=f"execution timed out after {TIMEOUT_SECONDS}s"
            )
        except Exception as exc:  # backstop — must never raise past here
            return ToolResult(ok=False, content="", error=f"unexpected error: {exc}")

        duration = round(time.perf_counter() - started, 3)
        stdout = truncate(completed.stdout or "", MAX_OUTPUT_CHARS)
        stderr = truncate(completed.stderr or "", MAX_OUTPUT_CHARS)
        ok = completed.returncode == 0

        return ToolResult(
            ok=ok,
            content=stdout,
            display={
                "stdout": stdout,
                "stderr": stderr,
                "returncode": completed.returncode,
                "duration_s": duration,
            },
            error=None if ok else (stderr.strip() or f"exited with code {completed.returncode}"),
        )
