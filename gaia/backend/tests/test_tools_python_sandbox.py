"""PythonSandboxTool: execution, isolation, timeout, and failure handling.

Every test that calls `execute()` depends on `gaia_env` — the tool reads
`config.sandbox_dir` and creates it, and this must never point at a real
user's data directory during tests.
"""

from __future__ import annotations

from gaia.tools.base import RiskLevel
from gaia.tools.python_sandbox import PythonSandboxTool


def test_python_sandbox_is_confirm_risk():
    # Arbitrary code execution is a different risk class from the calculator's
    # closed grammar — see the module docstring for why this must stay CONFIRM.
    assert PythonSandboxTool.risk_level is RiskLevel.CONFIRM


async def test_execute_returns_stdout(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "print(2 + 2)"})
    assert result.ok is True
    assert result.content.strip() == "4"
    assert result.display["returncode"] == 0


async def test_execute_captures_multiple_prints(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "for i in range(3):\n    print(i)"})
    assert result.ok is True
    assert result.content.split() == ["0", "1", "2"]


async def test_execute_reports_uncaught_exception_without_raising(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "raise ValueError('boom')"})
    assert result.ok is False
    assert result.display["returncode"] != 0
    assert "boom" in (result.error or "")


async def test_execute_syntax_error_is_reported_not_raised(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "def broken(:"})
    assert result.ok is False
    assert result.error


async def test_execute_times_out_on_infinite_loop(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "while True:\n    pass"})
    assert result.ok is False
    assert "timed out" in (result.error or "")


async def test_execute_rejects_non_string_code(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": 12345})
    assert result.ok is False
    assert "must be a non-empty string" in (result.error or "")


async def test_execute_rejects_empty_code(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "   "})
    assert result.ok is False


async def test_execute_rejects_overlong_code(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "print(1)\n" * 5000})
    assert result.ok is False
    assert "too long" in (result.error or "")


async def test_sandboxed_process_does_not_see_backend_secrets(gaia_env, monkeypatch):
    # The child gets a minimal allowlisted environment — a variable the
    # backend process holds (e.g. an API key set via .env) must not appear.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "import os; print('ANTHROPIC_API_KEY' in os.environ)"})
    assert result.ok is True
    assert result.content.strip() == "False"


async def test_sandboxed_process_runs_in_the_sandbox_directory(gaia_env):
    tool = PythonSandboxTool()
    result = await tool.execute({"code": "import os; print(os.getcwd())"})
    assert result.ok is True
    from gaia.config import get_settings

    assert result.content.strip() == str(get_settings().sandbox_dir)
