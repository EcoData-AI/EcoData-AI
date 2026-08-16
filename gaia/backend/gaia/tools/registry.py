"""Tool registry — the single place that knows which tools exist.

Mirrors `gaia.llm.registry` deliberately. The one rule this file enforces: a
`BLOCKED` tool is filtered out here, before the model ever sees its name — the
same "an unbuilt feature cannot look built in one place and unbuilt in
another" rule `core/capabilities.py` already applies to navigation.
"""

from __future__ import annotations

from gaia.tools.base import RiskLevel, Tool
from gaia.tools.calculator import CalculatorTool

TOOL_CLASSES: dict[str, type[Tool]] = {
    CalculatorTool.name: CalculatorTool,
}


def available_tools() -> list[Tool]:
    """Instantiated tools the model is allowed to know about and call."""
    return [cls() for cls in TOOL_CLASSES.values() if cls.risk_level is not RiskLevel.BLOCKED]


def tool_specs_for_provider() -> list[dict]:
    """Provider-neutral tool specs for `LLMProvider.stream_chat(tools=...)`."""
    return [tool.spec().to_dict() for tool in available_tools()]


def get_tool(name: str) -> Tool | None:
    """Look up a tool by name. `None` for an unknown *or* BLOCKED tool — the
    caller should treat both the same way: as a tool that cannot run."""
    cls = TOOL_CLASSES.get(name)
    if cls is None or cls.risk_level is RiskLevel.BLOCKED:
        return None
    return cls()
