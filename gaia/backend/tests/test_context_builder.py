from __future__ import annotations

from gaia.core.context_builder import build_context, estimate_tokens
from gaia.db.models import Message


def make_message(role: str, content: str, sequence: int, status: str = "complete") -> Message:
    return Message(
        conversation_id="c",
        role=role,
        content=content,
        sequence=sequence,
        status=status,
    )


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
