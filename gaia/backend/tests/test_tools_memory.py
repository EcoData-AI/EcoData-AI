"""RememberTool: the only writer of `Memory` rows.

Needs `gaia_env` (via `session`) — the tool opens its own database session.
"""

from __future__ import annotations

from gaia.services import memory_service
from gaia.tools.base import RiskLevel
from gaia.tools.memory import RememberTool


def test_remember_tool_is_confirm_risk():
    assert RememberTool.risk_level is RiskLevel.CONFIRM


async def test_remember_stores_a_semantic_memory_by_default(session):
    tool = RememberTool()
    result = await tool.execute({"content": "prefers formal notation"})

    assert result.ok is True
    assert "prefers formal notation" in result.content
    assert result.display == {"kind": "semantic", "content": "prefers formal notation"}

    memories = memory_service.list_memories(session)
    assert len(memories) == 1
    assert memories[0].kind == "semantic"
    assert memories[0].content == "prefers formal notation"


async def test_remember_accepts_an_episodic_kind(session):
    tool = RememberTool()
    result = await tool.execute({"content": "asked about Cournot competition", "kind": "episodic"})

    assert result.ok is True
    memories = memory_service.list_memories(session)
    assert memories[0].kind == "episodic"


async def test_remember_rejects_empty_content():
    tool = RememberTool()
    result = await tool.execute({"content": "   "})
    assert result.ok is False
    assert "content" in (result.error or "")


async def test_remember_rejects_missing_content():
    tool = RememberTool()
    result = await tool.execute({})
    assert result.ok is False


async def test_remember_rejects_invalid_kind(session):
    # Needs `session` (a real, isolated `gaia_env`) — unlike the empty/missing
    # content cases above, this one passes validation and reaches
    # `session_scope()`, so it must not run against the developer's real data
    # directory.
    tool = RememberTool()
    result = await tool.execute({"content": "a fact", "kind": "project"})
    assert result.ok is False
    assert "kind" in (result.error or "")
