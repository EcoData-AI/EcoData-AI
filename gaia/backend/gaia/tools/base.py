"""Tool interface — the contract every GAIA tool implements.

Mirrors `gaia.llm.base.LLMProvider` on purpose: a small ABC, a result type that
carries failure without raising, and a risk level expressed as a class
attribute the tool itself declares. That last point is load-bearing: risk level
is never something the model or the request can set — the registry (`registry.py`)
is the enforcement point, not the tool's own judgment or the provider's output.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    #: Executes immediately, no user approval. Reserved for tools with no side
    #: effects outside their own computation — e.g. the calculator.
    SAFE = "safe"
    #: Advertised to the model, but execution pauses for the user to approve or
    #: deny before it runs. For tools with real-world side effects (filesystem
    #: writes, terminal commands).
    CONFIRM = "confirm"
    #: Never advertised to the model and never executed. A disabled or
    #: not-yet-ready tool stays fully defined in code but invisible at
    #: runtime — the same "an unbuilt feature cannot look built" rule
    #: `core/capabilities.py` already enforces for navigation.
    BLOCKED = "blocked"


@dataclass(slots=True)
class ToolResult:
    """What a tool execution produced. Never raise instead of returning one."""

    ok: bool
    #: Fed back to the model as the tool result's text content.
    content: str
    #: Optional structured payload for the UI to render without re-parsing
    #: `content` (e.g. the calculator's `{"expression", "result"}`).
    display: dict[str, Any] | None = None
    #: Plain-language failure reason, set when `ok` is False.
    error: str | None = None


@dataclass(slots=True)
class ToolSpec:
    """Provider-neutral tool description, handed to `LLMProvider.stream_chat`."""

    name: str
    description: str
    #: JSON Schema for the arguments object.
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class Tool(abc.ABC):
    """Contract every tool implements.

    Implementations must be safe to construct with no arguments; all I/O and
    computation happens in `execute()`.
    """

    #: stable identifier the model refers to by name
    name: str = "abstract"
    #: shown to the model so it knows when and how to call this tool
    description: str = ""
    #: JSON Schema for the arguments object `execute()` expects
    parameters: dict[str, Any] = {}
    #: safest default; a tool must deliberately opt into a lower bar than CONFIRM
    risk_level: RiskLevel = RiskLevel.CONFIRM

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Run the tool. Must never raise — failures are a `ToolResult(ok=False, ...)`."""
