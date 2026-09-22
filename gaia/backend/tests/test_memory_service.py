from __future__ import annotations

import pytest

from gaia.services import memory_service
from gaia.services.memory_service import MemoryError


def test_create_memory_rejects_unknown_kind(session):
    with pytest.raises(MemoryError):
        memory_service.create_memory(session, kind="project", content="a fact")


def test_create_memory_rejects_empty_content(session):
    with pytest.raises(MemoryError):
        memory_service.create_memory(session, kind="semantic", content="   ")


def test_create_and_list_memory(session):
    memory_service.create_memory(session, kind="semantic", content="prefers formal notation")
    memories = memory_service.list_memories(session)
    assert len(memories) == 1
    assert memories[0].kind == "semantic"
    assert memories[0].enabled is True


def test_list_memories_filters_by_kind_and_query(session):
    memory_service.create_memory(session, kind="semantic", content="likes tea")
    memory_service.create_memory(session, kind="episodic", content="asked about game theory")

    assert len(memory_service.list_memories(session, kind="semantic")) == 1
    assert len(memory_service.list_memories(session, query="game theory")) == 1
    assert len(memory_service.list_memories(session, query="nonexistent")) == 0


def test_update_memory_content_importance_and_enabled(session):
    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")

    updated = memory_service.update_memory(session, memory.id, content="likes coffee")
    assert updated.content == "likes coffee"

    updated = memory_service.update_memory(session, memory.id, importance=0.9)
    assert updated.importance == 0.9

    updated = memory_service.update_memory(session, memory.id, enabled=False)
    assert updated.enabled is False


def test_update_memory_rejects_empty_content(session):
    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")
    with pytest.raises(MemoryError):
        memory_service.update_memory(session, memory.id, content="   ")


def test_update_unknown_memory_returns_none(session):
    assert memory_service.update_memory(session, "no-such-id", content="x") is None


def test_delete_memory(session):
    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")
    assert memory_service.delete_memory(session, memory.id) is True
    assert memory_service.list_memories(session) == []
    assert memory_service.delete_memory(session, memory.id) is False


def test_relevant_memories_excludes_disabled_and_orders_by_importance(session):
    low = memory_service.create_memory(
        session, kind="semantic", content="low importance", importance=0.1
    )
    high = memory_service.create_memory(
        session, kind="semantic", content="high importance", importance=0.9
    )
    disabled = memory_service.create_memory(session, kind="semantic", content="disabled")
    memory_service.update_memory(session, disabled.id, enabled=False)

    relevant = memory_service.relevant_memories(session)
    assert [m.id for m in relevant] == [high.id, low.id]


def test_relevant_memories_respects_limit(session):
    for i in range(5):
        memory_service.create_memory(session, kind="semantic", content=f"fact {i}")
    assert len(memory_service.relevant_memories(session, limit=2)) == 2


def test_mark_used_sets_last_used_at(session):
    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")
    assert memory.last_used_at is None

    memory_service.mark_used(session, [memory.id])
    session.refresh(memory)
    assert memory.last_used_at is not None
