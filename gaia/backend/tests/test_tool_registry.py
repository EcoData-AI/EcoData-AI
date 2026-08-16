"""Tool registry: calculator is discoverable, and BLOCKED tools stay invisible."""

from __future__ import annotations

from gaia.tools.base import RiskLevel, Tool, ToolResult
from gaia.tools.calculator import CalculatorTool
from gaia.tools.registry import TOOL_CLASSES, available_tools, get_tool, tool_specs_for_provider


class _DummyBlockedTool(Tool):
    name = "dummy_blocked"
    description = "A tool that exists in code but must never be reachable."
    parameters = {"type": "object", "properties": {}}
    risk_level = RiskLevel.BLOCKED

    async def execute(self, arguments: dict) -> ToolResult:  # pragma: no cover - never called
        return ToolResult(ok=True, content="should never run")


def test_calculator_is_registered():
    assert "calculator" in TOOL_CLASSES
    assert get_tool("calculator") is not None
    assert any(t.name == "calculator" for t in available_tools())


def test_unknown_tool_name_returns_none():
    assert get_tool("does_not_exist") is None


def test_tool_specs_shape_matches_provider_expectations():
    specs = tool_specs_for_provider()
    calc_spec = next(s for s in specs if s["name"] == "calculator")
    assert set(calc_spec.keys()) == {"name", "description", "parameters"}
    assert calc_spec["parameters"]["type"] == "object"
    assert "expression" in calc_spec["parameters"]["properties"]


def test_blocked_tool_is_excluded_from_available_tools(monkeypatch):
    monkeypatch.setitem(TOOL_CLASSES, _DummyBlockedTool.name, _DummyBlockedTool)
    assert all(t.name != "dummy_blocked" for t in available_tools())


def test_blocked_tool_is_excluded_from_provider_specs(monkeypatch):
    monkeypatch.setitem(TOOL_CLASSES, _DummyBlockedTool.name, _DummyBlockedTool)
    specs = tool_specs_for_provider()
    assert all(s["name"] != "dummy_blocked" for s in specs)


def test_blocked_tool_get_tool_returns_none(monkeypatch):
    monkeypatch.setitem(TOOL_CLASSES, _DummyBlockedTool.name, _DummyBlockedTool)
    assert get_tool("dummy_blocked") is None


def test_calculator_class_matches_registry_entry():
    assert TOOL_CLASSES["calculator"] is CalculatorTool
