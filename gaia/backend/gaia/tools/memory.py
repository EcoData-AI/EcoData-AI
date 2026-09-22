"""Remember — the only writer of persistent `Memory` rows.

CONFIRM-risk, same gate as `filesystem_write`/`terminal`: the user sees exactly
what will be stored before it happens, which is what makes this "opt-in
capture, never automatic" real rather than a system-prompt suggestion. The
system prompt (`core/persona.py`) additionally instructs the model to call
this only when the user explicitly asks to remember something — the CONFIRM
gate is the backstop if that instruction is ever ignored.

Tools have no request-scoped DB session (see `services/workspace_service.py`'s
`_enabled_roots()` for the same pattern), so `execute()` opens its own
`session_scope()`.
"""

from __future__ import annotations

from typing import Any

from gaia.db.session import session_scope
from gaia.services import memory_service
from gaia.services.memory_service import ALLOWED_KINDS, MemoryError
from gaia.tools.base import RiskLevel, Tool, ToolResult


class RememberTool(Tool):
    name = "remember"
    description = (
        "Store a fact, preference, or note the user has explicitly asked you to "
        "remember, so it can inform future conversations. Only call this when the "
        "user actually asked you to remember something — never to record an "
        "inference you made on your own."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The fact or preference to remember, in the user's own terms.",
            },
            "kind": {
                "type": "string",
                "enum": list(ALLOWED_KINDS),
                "description": (
                    "'semantic' for a durable fact or preference (default); "
                    "'episodic' for something specific to remember from this conversation."
                ),
            },
        },
        "required": ["content"],
    }
    risk_level = RiskLevel.CONFIRM

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content")
        kind = arguments.get("kind", "semantic")

        if not isinstance(content, str) or not content.strip():
            return ToolResult(ok=False, content="", error="'content' must be a non-empty string")
        if not isinstance(kind, str):
            return ToolResult(ok=False, content="", error="'kind' must be a string")

        try:
            with session_scope() as session:
                memory = memory_service.create_memory(session, kind=kind, content=content)
                stored_kind, stored_content = memory.kind, memory.content
        except MemoryError as exc:
            return ToolResult(ok=False, content="", error=str(exc))
        except Exception as exc:  # backstop — must never raise past here
            return ToolResult(ok=False, content="", error=f"unexpected error: {exc}")

        return ToolResult(
            ok=True,
            content=f"Remembered ({stored_kind}): {stored_content}",
            display={"kind": stored_kind, "content": stored_content},
        )
