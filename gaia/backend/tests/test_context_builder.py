from __future__ import annotations

from gaia.core.context_builder import build_context, estimate_tokens
from gaia.db.models import Memory, Message, Project, ProjectTask


def make_message(role: str, content: str, sequence: int, status: str = "complete") -> Message:
    return Message(
        conversation_id="c",
        role=role,
        content=content,
        sequence=sequence,
        status=status,
    )


def make_memory(kind: str, content: str) -> Memory:
    return Memory(kind=kind, content=content)


def make_project(name: str, **kwargs) -> Project:
    return Project(name=name, **kwargs)


def make_task(title: str) -> ProjectTask:
    return ProjectTask(project_id="p", title=title)


def test_includes_persona_and_history():
    history = [make_message("user", "hello", 1), make_message("assistant", "hi", 2)]
    context = build_context(history=history, context_window=200_000)

    assert "You are GAIA" in context.system
    assert "not conscious" in context.system
    assert [(m.role, m.content) for m in context.messages] == [
        ("user", "hello"),
        ("assistant", "hi"),
    ]
    assert context.dropped_message_count == 0


def test_skips_streaming_and_errored_messages():
    history = [
        make_message("user", "hello", 1),
        make_message("assistant", "partial", 2, status="error"),
        make_message("user", "again", 3),
        make_message("assistant", "mid-stream", 4, status="streaming"),
    ]
    context = build_context(history=history, context_window=200_000)
    assert [m.content for m in context.messages] == ["hello", "again"]


def test_drops_oldest_when_over_budget():
    # A tiny window forces trimming; the most recent turns must survive.
    history = [
        make_message("user" if i % 2 == 0 else "assistant", "x" * 4000, i + 1)
        for i in range(20)
    ]
    context = build_context(history=history, context_window=8_000)

    assert context.dropped_message_count > 0
    assert len(context.messages) < len(history)
    # The newest message is always kept.
    assert context.messages[-1].content == history[-1].content


def test_history_never_starts_with_an_assistant_turn():
    history = [make_message("assistant", "orphan reply", 1), make_message("user", "hi", 2)]
    context = build_context(history=history, context_window=200_000)
    assert context.messages[0].role == "user"


def test_custom_and_conversation_instructions_are_applied():
    context = build_context(
        history=[make_message("user", "hi", 1)],
        context_window=200_000,
        custom_instructions="Always answer in French.",
        conversation_system_prompt="This thread is about game theory.",
        summary="Earlier we discussed Cournot competition.",
    )
    assert "Always answer in French." in context.system
    assert "This thread is about game theory." in context.system
    assert "Cournot competition" in context.system
    assert set(context.sources) >= {
        "persona",
        "custom_instructions",
        "conversation_instructions",
        "conversation_summary",
    }


def test_unknown_context_window_falls_back_without_crashing():
    context = build_context(history=[make_message("user", "hi", 1)], context_window=0)
    assert context.messages


def test_token_estimate_is_monotonic():
    assert estimate_tokens("short") < estimate_tokens("a much longer string of text here")


def test_memories_are_injected_into_the_system_prompt():
    context = build_context(
        history=[make_message("user", "hi", 1)],
        context_window=200_000,
        memories=[make_memory("semantic", "prefers formal notation")],
    )
    assert "prefers formal notation" in context.system
    assert "memory" in context.sources


def test_no_memories_means_no_memory_section_or_source():
    context = build_context(history=[make_message("user", "hi", 1)], context_window=200_000)
    assert "Things to remember" not in context.system
    assert "memory" not in context.sources


def test_oldest_kept_sequence_is_none_when_nothing_is_dropped():
    context = build_context(history=[make_message("user", "hi", 1)], context_window=200_000)
    assert context.oldest_kept_sequence is None


def test_oldest_kept_sequence_marks_the_boundary_when_messages_are_dropped():
    history = [
        make_message("user" if i % 2 == 0 else "assistant", "x" * 4000, i + 1)
        for i in range(20)
    ]
    context = build_context(history=history, context_window=8_000)

    assert context.dropped_message_count > 0
    # The boundary is exactly the sequence of the first message actually kept
    # — here, the tail of `history` of length `len(context.messages)`.
    expected_first_kept = history[len(history) - len(context.messages)]
    assert context.oldest_kept_sequence == expected_first_kept.sequence


def test_project_is_injected_into_the_system_prompt():
    project = make_project("Cosmos Simulator", description="A physics sandbox", goals="N-body")
    context = build_context(
        history=[make_message("user", "hi", 1)],
        context_window=200_000,
        project=project,
        project_tasks=[make_task("design API"), make_task("scaffold repo")],
    )
    assert "Cosmos Simulator" in context.system
    assert "A physics sandbox" in context.system
    assert "N-body" in context.system
    assert "design API" in context.system
    assert "scaffold repo" in context.system
    assert "project" in context.sources


def test_no_project_means_no_project_section_or_source():
    context = build_context(history=[make_message("user", "hi", 1)], context_window=200_000)
    # `## Current project` (the injected section header), not the bare phrase —
    # the persona's own base prompt mentions "Current project" descriptively
    # (quoted, no `##`) regardless of whether one is actually assigned.
    assert "## Current project" not in context.system
    assert "project" not in context.sources


def test_project_with_no_description_or_tasks_still_shows_its_name():
    context = build_context(
        history=[make_message("user", "hi", 1)],
        context_window=200_000,
        project=make_project("Cosmos Simulator"),
    )
    assert "Cosmos Simulator" in context.system
    assert "project" in context.sources
