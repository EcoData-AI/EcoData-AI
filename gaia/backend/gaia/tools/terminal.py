"""Terminal — a CONFIRM-risk tool. Runs a shell command in an isolated subprocess.

Every call requires the user's explicit approval, and shows them the exact
command before it runs — that transparency is the primary defence. On top of
it, a small set of unambiguously destructive patterns is refused even after
approval, matching docs/SECURITY.md's own risk table, which puts "recursive
deletion, partition changes, disabling protections" at BLOCKED-tier, not
merely CONFIRM-tier: ordinary approval isn't meant to be enough for those.

**This blocklist is pattern matching on the command's tokens, not a security
boundary.** It stops the obvious, literal forms — `rm -rf`, `format C:`,
`diskpart`, disabling Windows Defender or a Linux firewall, the classic
fork-bomb signature. It does **not** stop deliberate evasion: variable
expansion, quoting tricks, aliases, a script that does the same thing
indirectly. Anyone who wants to get past it with intent can. What it is meant
to catch is a model asking for something catastrophic in the plain, ordinary
way models actually phrase things — not a determined adversary.

Runs the same workspace-scoped model as `filesystem.py`: the command's `cwd`
must resolve inside an enabled, writable `WorkspaceRoot`
(`services/workspace_service.resolve_within_workspace`) — writable is
required even for a read-only-looking command, because a shell can always do
more than it appears to.

What *is* enforced beyond the blocklist and the confirmation gate:
a wall-clock timeout, a sanitised environment (GAIA's own secrets are never
in it — see core/secrets.py), and — POSIX only — memory/CPU/process-count
limits via `resource.setrlimit`. Windows has no equivalent stdlib mechanism,
so on Windows the wall-clock timeout is the only resource ceiling, exactly
the same disclosed gap as `python_sandbox.py`.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from typing import Any

from gaia.services.workspace_service import WorkspaceAccessError, resolve_within_workspace
from gaia.tools._process_safety import minimal_environment, posix_resource_limits, truncate
from gaia.tools.base import RiskLevel, Tool, ToolResult

MAX_COMMAND_LENGTH = 4_000
TIMEOUT_SECONDS = 30
MAX_OUTPUT_CHARS = 20_000
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MB — POSIX only
CPU_TIME_LIMIT_SECONDS = 30  # POSIX only

_ENV_ALLOWLIST = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "COMSPEC",
    "PATHEXT",
)


def _tokenize(command: str) -> list[str]:
    """Best-effort split into shell-like tokens. Never raises: a command with
    unbalanced quotes just falls back to a plain whitespace split, which is
    still good enough for the pattern checks below."""
    try:
        return shlex.split(command, posix=(os.name != "nt"))
    except ValueError:
        return command.split()


def _basenames(tokens: list[str]) -> list[str]:
    return [t.replace("\\", "/").rsplit("/", 1)[-1].lower() for t in tokens]


def _has_word_flag(tokens: list[str], *names: str) -> bool:
    """A dash-prefixed token matching one of `names` exactly, after stripping
    leading dashes — covers both `--recursive` and PowerShell's single-dash,
    full-word style (`-Recurse`, `-DisableRealtimeMonitoring`)."""
    wanted = {n.lower() for n in names}
    return any(t.lstrip("-").lower() in wanted for t in tokens if t.startswith("-"))


def _has_short_cluster_flag(tokens: list[str], letter: str) -> bool:
    """A single-dash Unix-style flag cluster (`-rf`) containing `letter`.

    Deliberately does not match `--{word}` or a bare `-{word}` — checking
    whether the letter merely *appears inside* a long flag name would treat
    `--force` as "contains f" and `rm --force` (without recursion) as
    equivalent to `rm -rf`, which it is not.
    """
    for tok in tokens:
        if len(tok) > 1 and tok[0] == "-" and tok[1] != "-" and letter in tok[1:].lower():
            return True
    return False


def _blocked_reason(command: str) -> str | None:
    tokens = _tokenize(command)
    basenames = _basenames(tokens)
    low = command.lower()

    if "rm" in basenames and (
        _has_short_cluster_flag(tokens, "r") or _has_word_flag(tokens, "recursive")
    ):
        return "recursive deletion (rm -r/--recursive)"
    if any(b in ("rd", "rmdir") for b in basenames) and any(
        t.lower() in ("/s", "-s") for t in tokens
    ):
        return "recursive directory deletion (rd/rmdir /s)"
    if "del" in basenames and any(t.lower() == "/s" for t in tokens):
        return "recursive file deletion (del /s)"
    if "remove-item" in basenames and _has_word_flag(tokens, "recurse", "r"):
        return "recursive deletion (Remove-Item -Recurse)"
    if any(b == "format" for b in basenames):
        return "disk formatting"
    if "diskpart" in basenames:
        return "disk partitioning"
    if any(b in ("mkfs", "fdisk") or b.startswith("mkfs.") for b in basenames):
        return "filesystem/partition creation"
    if "dd" in basenames and any(t.lower().startswith("of=/dev/") for t in tokens):
        return "raw disk write (dd)"
    if "set-mppreference" in basenames and _has_word_flag(tokens, "disablerealtimemonitoring"):
        return "disabling Windows Defender"
    if "netsh" in low and "advfirewall" in low and re.search(r"state\s+off", low):
        return "disabling the Windows firewall"
    if re.search(r"\bsc\s+(config|stop)\s+(windefend|mpssvc|wuauserv)\b", low):
        return "disabling a Windows security/update service"
    if re.search(r"systemctl\s+(stop|disable)\s+(ufw|firewalld|apparmor)\b", low):
        return "disabling a Linux firewall/security service"
    if re.search(r"\bsetenforce\s+0\b", low):
        return "disabling SELinux enforcement"
    if re.search(r":\(\)\s*\{\s*:\|:&\s*\};\s*:", command):
        return "a classic fork bomb"
    if re.search(r"%0\s*\|\s*%0", command):
        return "a Windows batch fork bomb"
    return None


class TerminalTool(Tool):
    name = "terminal"
    description = (
        "Run a shell command in an explicitly allowed, writable workspace root. "
        "Requires the user's approval before every call, and shows them the "
        "exact command. A small set of unambiguously destructive patterns "
        "(recursive deletion, disk formatting, disabling security software, "
        "fork bombs) is refused even after approval. Runs with a wall-clock "
        "timeout."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run, exactly as it should execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Absolute path to an allowed, writable workspace root "
                "(or a subdirectory of one) to run the command in.",
            },
        },
        "required": ["command", "cwd"],
    }
    risk_level = RiskLevel.CONFIRM

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command")
        cwd_raw = arguments.get("cwd")

        if not isinstance(command, str) or not command.strip():
            return ToolResult(ok=False, content="", error="'command' must be a non-empty string")
        if not isinstance(cwd_raw, str):
            return ToolResult(ok=False, content="", error="'cwd' must be a string")
        if len(command) > MAX_COMMAND_LENGTH:
            return ToolResult(
                ok=False,
                content="",
                error=f"command too long (limit {MAX_COMMAND_LENGTH} characters)",
            )

        reason = _blocked_reason(command)
        if reason is not None:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"refused: this command matches a blocked pattern ({reason}). "
                    "This is a policy refusal, not an execution failure — the command "
                    "did not run."
                ),
            )

        try:
            resolved_cwd = resolve_within_workspace(cwd_raw, require_writable=True)
        except WorkspaceAccessError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        if not resolved_cwd.is_dir():
            return ToolResult(
                ok=False, content="", error=f"'{cwd_raw}' is not an existing directory"
            )

        popen_kwargs: dict[str, Any] = {}
        if os.name == "posix":
            popen_kwargs["preexec_fn"] = posix_resource_limits(
                memory_bytes=MEMORY_LIMIT_BYTES, cpu_seconds=CPU_TIME_LIMIT_SECONDS
            )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(resolved_cwd),
                env=minimal_environment(_ENV_ALLOWLIST),
                timeout=TIMEOUT_SECONDS,
                **popen_kwargs,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False, content="", error=f"command timed out after {TIMEOUT_SECONDS}s"
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
                "command": command,
                "cwd": str(resolved_cwd),
                "stdout": stdout,
                "stderr": stderr,
                "returncode": completed.returncode,
                "duration_s": duration,
            },
            error=None if ok else (stderr.strip() or f"exited with code {completed.returncode}"),
        )
