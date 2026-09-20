"""Terminal tool: execution, workspace containment, and the blocklist backstop.

Every test that calls `execute()` needs `session` (→ `gaia_env`) since the
tool queries `WorkspaceRoot` rows via a real database session.
"""

from __future__ import annotations

import sys

import pytest

from gaia.services import workspace_service
from gaia.tools.base import RiskLevel
from gaia.tools.terminal import TerminalTool, _blocked_reason


def test_terminal_is_confirm_risk():
    assert TerminalTool.risk_level is RiskLevel.CONFIRM


# --------------------------------------------------------------- execution


async def test_execute_runs_a_command_and_captures_stdout(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    tool = TerminalTool()
    result = await tool.execute(
        {"cwd": str(workspace), "command": f'"{sys.executable}" -c "print(1 + 1)"'}
    )
    assert result.ok is True
    assert result.content.strip() == "2"
    assert result.display["returncode"] == 0


async def test_execute_reports_nonzero_exit_without_raising(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    tool = TerminalTool()
    result = await tool.execute(
        {"cwd": str(workspace), "command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'}
    )
    assert result.ok is False
    assert result.display["returncode"] == 3


async def test_execute_times_out(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    import gaia.tools.terminal as terminal_module

    terminal_module.TIMEOUT_SECONDS = 1
    try:
        tool = TerminalTool()
        result = await tool.execute(
            {
                "cwd": str(workspace),
                "command": f'"{sys.executable}" -c "import time; time.sleep(5)"',
            }
        )
        assert result.ok is False
        assert "timed out" in (result.error or "")
    finally:
        terminal_module.TIMEOUT_SECONDS = 30


async def test_execute_runs_in_the_given_cwd(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "marker.txt").write_text("here")
    workspace_service.add_root(session, path=str(workspace), writable=True)

    tool = TerminalTool()
    result = await tool.execute(
        {
            "cwd": str(workspace),
            "command": f'"{sys.executable}" -c "import os; print(os.path.exists(\'marker.txt\'))"',
        }
    )
    assert result.ok is True
    assert result.content.strip() == "True"


# --------------------------------------------------------------- workspace containment


async def test_execute_rejects_readonly_root(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=False)

    tool = TerminalTool()
    result = await tool.execute({"cwd": str(workspace), "command": "echo hi"})
    assert result.ok is False
    assert "read-only" in (result.error or "")


async def test_execute_rejects_cwd_outside_any_root(session, tmp_path):
    inside = tmp_path / "workspace"
    inside.mkdir()
    workspace_service.add_root(session, path=str(inside), writable=True)

    tool = TerminalTool()
    result = await tool.execute({"cwd": str(tmp_path), "command": "echo hi"})
    assert result.ok is False
    assert "not inside any allowed workspace" in (result.error or "")


async def test_execute_with_no_workspace_roots_configured(session, tmp_path):
    tool = TerminalTool()
    result = await tool.execute({"cwd": str(tmp_path), "command": "echo hi"})
    assert result.ok is False
    assert "No workspace roots are configured" in (result.error or "")


async def test_execute_rejects_missing_cwd(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    tool = TerminalTool()
    result = await tool.execute({"cwd": str(workspace / "nope"), "command": "echo hi"})
    assert result.ok is False


# --------------------------------------------------------------- argument validation


async def test_execute_rejects_non_string_command(session):
    tool = TerminalTool()
    result = await tool.execute({"cwd": "/tmp", "command": 123})
    assert result.ok is False
    assert "must be a non-empty string" in (result.error or "")


async def test_execute_rejects_empty_command(session):
    tool = TerminalTool()
    result = await tool.execute({"cwd": "/tmp", "command": "   "})
    assert result.ok is False


async def test_execute_rejects_overlong_command(session):
    tool = TerminalTool()
    result = await tool.execute({"cwd": "/tmp", "command": "echo " + "x" * 5000})
    assert result.ok is False
    assert "too long" in (result.error or "")


# --------------------------------------------------------------- the blocklist backstop


async def test_blocked_command_is_refused_even_when_workspace_is_writable(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    tool = TerminalTool()
    result = await tool.execute({"cwd": str(workspace), "command": "rm -rf ./everything"})
    assert result.ok is False
    assert "refused" in (result.error or "")
    assert "policy refusal" in (result.error or "")


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /some/path",
        "rm -fr /some/path",
        "rm --recursive /some/path",
        "rd /s C:\\some\\path",
        "rmdir /s C:\\some\\path",
        "del /s /q C:\\some\\path",
        "Remove-Item -Recurse -Force C:\\some\\path",
        "format C:",
        "diskpart",
        "mkfs.ext4 /dev/sda1",
        "fdisk /dev/sda",
        "dd if=/dev/zero of=/dev/sda",
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        "netsh advfirewall set allprofiles state off",
        "sc config WinDefend start= disabled",
        "systemctl stop firewalld",
        "setenforce 0",
        ":(){ :|:& };:",
        "%0|%0",
    ],
)
def test_blocked_reason_catches_known_dangerous_commands(command):
    assert _blocked_reason(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "echo hello",
        "dir",
        "ls -la",
        "git status",
        "git push --force",  # not `rm`; must not be caught by the rm heuristic
        "python --version",
        "npm install",
        "rm file.txt",  # no recursion flag
        "del file.txt",  # no /s
        "docker rm -f container_id",  # force but not recursive
        "echo 'reformat my thinking, not my disk'",  # contains the word "format"-ish text
    ],
)
def test_blocked_reason_does_not_flag_ordinary_commands(command):
    assert _blocked_reason(command) is None
