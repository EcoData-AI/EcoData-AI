"""Conversation summarisation — the gap `docs/ARCHITECTURE.md`'s "Known limits"
flagged: the `Conversation.summary`/`summarized_through` columns and the
`context_builder` hook that consumes them already existed, but nothing wrote
to them, so a long conversation just dropped its oldest turns.

`summarize_if_needed` is the pure, directly-testable core: given a
`BuiltContext.oldest_kept_sequence` (the boundary past which messages are now
at risk of falling out of context), it summarises everything between the
conversation's last summarised point and that boundary, folding it into the
existing summary.

`summarize_in_background` is the thin wrapper `chat_service` fires as a
detached `asyncio.Task` after a turn completes. It is detached rather than
awaited inline because the SSE generator it would otherwise run inside can be
cancelled the instant the client consumes the `done` event — tying
summarisation to that request's lifecycle risks it never running at all. A
failure here must never surface as a chat-turn error; the next turn simply
tries again from the same `summarized_through` boundary.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from gaia.db.models import Conversation, Message
from gaia.db.session import session_scope
from gaia.llm.base import ChatMessage, LLMProvider, ProviderError
from gaia.llm.registry import build_provider
from gaia.services import conversation_service

logger = logging.getLogger("gaia.summarization")

SUMMARY_MAX_TOKENS = 400


def _build_prompt(existing_summary: str | None, transcript: str) -> str:
    parts = [
        "Summarise the following excerpt from an ongoing conversation between a "
        "user and an AI assistant. Preserve concrete facts, decisions, and "
        "stated preferences that would matter for later turns. Be concise — a "
        "few sentences, not a transcript. Respond with the summary text only, "
        "no preamble.",
    ]
    if existing_summary and existing_summary.strip():
        parts.append(
            f"\nExisting summary of everything before this excerpt:\n{existing_summary.strip()}"
        )
    parts.append(f"\nNew excerpt to fold in:\n{transcript}")
    return "\n".join(parts)


async def _complete(provider: LLMProvider, model_id: str, prompt: str) -> str:
    """Drain a non-tool `stream_chat` call into a single string."""
    chunks: list[str] = []
    async for event in provider.stream_chat(
        [ChatMessage(role="user", content=prompt)],
        model=model_id,
        max_tokens=SUMMARY_MAX_TOKENS,
        tools=None,
    ):
        if event.type == "text":
            chunks.append(event.text)
        elif event.type == "error":
            raise ProviderError(
                (event.error or {}).get("message", "summarisation failed"),
            )
    return "".join(chunks)


async def summarize_if_needed(
    session: Session,
    conversation: Conversation,
    history: list[Message],
    oldest_kept_sequence: int | None,
    provider: LLMProvider,
    model_id: str,
) -> None:
    if oldest_kept_sequence is None:
        return

    pending = [
        m
        for m in history
        if conversation.summarized_through < m.sequence < oldest_kept_sequence
        and m.role in ("user", "assistant")
        and m.status == "complete"
        and m.content.strip()
    ]
    if not pending:
        return

    transcript = "\n".join(f"{m.role}: {m.content}" for m in pending)
    prompt = _build_prompt(conversation.summary, transcript)

    try:
        text = await _complete(provider, model_id, prompt)
    except ProviderError:
        logger.warning(
            "conversation summarisation failed; will retry next turn",
            extra={"conversation_id": conversation.id},
        )
        return

    text = text.strip()
    if not text:
        return

    conversation.summary = text
    conversation.summarized_through = pending[-1].sequence
    session.commit()


async def summarize_in_background(
    *, conversation_id: str, oldest_kept_sequence: int, provider_id: str, model_id: str
) -> None:
    """Fired as a detached task by `chat_service` with the exact boundary that
    turn's own `build_context` computed — recomputing it here would mean
    duplicating (and risking drift from) `context_builder`'s budgeting logic.
    """
    try:
        with session_scope() as session:
            conversation = conversation_service.get_conversation(session, conversation_id)
            if conversation is None:
                return
            history = conversation_service.get_messages(session, conversation_id)
            provider = build_provider(session, provider_id)
            await summarize_if_needed(
                session, conversation, history, oldest_kept_sequence, provider, model_id
            )
    except Exception:  # noqa: BLE001 - a background task must never crash the process
        logger.exception(
            "conversation summarisation task failed", extra={"conversation_id": conversation_id}
        )
