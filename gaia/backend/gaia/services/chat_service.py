"""The chat turn: context → provider → stream → persist.

Emits Server-Sent Events so the UI can render tokens as they arrive. The
assistant message row is created *before* streaming starts with status
"streaming", then filled in as text arrives. That means an interrupted turn
leaves a visible partial message with an honest status rather than vanishing.

Database calls here are synchronous SQLAlchemy against local SQLite, where a
write is sub-millisecond; they run inline rather than in a threadpool. If the
storage backend ever moves off local SQLite this becomes a real blocking
concern and should move to the async engine.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from gaia.core.context_builder import build_context
from gaia.db.base import utcnow
from gaia.db.models import Message, TaskRun
from gaia.llm.base import LLMProvider, ProviderError
from gaia.llm.registry import build_provider
from gaia.services import conversation_service, settings_service

logger = logging.getLogger("gaia.chat")


@dataclass(slots=True)
class TurnRequest:
    conversation_id: str
    content: str
    provider_id: str | None = None
    model_id: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _resolve(session: Session, request: TurnRequest) -> tuple[LLMProvider, str, int]:
    """Pick the provider and model for this turn, and find the context window."""
    provider_id = request.provider_id or settings_service.get_active_provider_id(session)
    provider = build_provider(session, provider_id)
    model_id = await provider.resolve_model(
        request.model_id or settings_service.get(session, settings_service.ACTIVE_MODEL)
    )
    models = await provider.list_models()
    info = next((m for m in models if m.id == model_id), None)
    return provider, model_id, (info.context_window if info else 0)


async def stream_turn(session: Session, request: TurnRequest) -> AsyncIterator[str]:
    conversation = conversation_service.get_conversation(session, request.conversation_id)
    if conversation is None:
        yield _sse("error", {"kind": "not_found", "message": "That conversation no longer exists."})
        return

    task = TaskRun(
        conversation_id=conversation.id,
        kind="chat",
        label="Chat response",
        status="running",
        started_at=utcnow(),
    )
    session.add(task)

    user_message = conversation_service.add_message(
        session, conversation, role="user", content=request.content
    )
    # First user message names the conversation.
    if conversation.title == conversation_service.DEFAULT_TITLE:
        conversation.title = conversation_service.derive_title(request.content)
        session.commit()

    yield _sse(
        "user_message",
        {"id": user_message.id, "sequence": user_message.sequence, "title": conversation.title},
    )

    try:
        provider, model_id, context_window = await _resolve(session, request)
    except ProviderError as exc:
        _fail_task(session, task, exc.message)
        yield _sse("error", exc.to_dict())
        return

    history = conversation_service.get_messages(session, conversation.id)
    context = build_context(
        history=history,
        context_window=context_window,
        custom_instructions=settings_service.get(session, settings_service.CUSTOM_INSTRUCTIONS),
        conversation_system_prompt=conversation.system_prompt,
        summary=conversation.summary,
    )

    assistant = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        sequence=conversation_service.next_sequence(session, conversation.id),
        status="streaming",
        provider_id=provider.id,
        model_id=model_id,
    )
    session.add(assistant)
    session.commit()
    session.refresh(assistant)

    yield _sse(
        "start",
        {
            "message_id": assistant.id,
            "sequence": assistant.sequence,
            "provider_id": provider.id,
            "model_id": model_id,
            "context": {
                "sources": context.sources,
                "estimated_input_tokens": context.estimated_input_tokens,
                "dropped_messages": context.dropped_message_count,
            },
        },
    )

    started = time.perf_counter()
    chunks: list[str] = []
    usage = None
    stop_reason = None
    failure: dict | None = None

    try:
        stream = provider.stream_chat(
            context.messages,
            model=model_id,
            system=context.system,
            temperature=float(settings_service.get(session, settings_service.TEMPERATURE) or 0.7),
            max_tokens=int(settings_service.get(session, settings_service.MAX_TOKENS) or 16000),
        )
        async for event in stream:
            if event.type == "text":
                chunks.append(event.text)
                yield _sse("delta", {"text": event.text})
            elif event.type == "usage":
                usage = event.usage
            elif event.type == "error":
                failure = event.error
                break
            elif event.type == "done":
                stop_reason = event.stop_reason
    except ProviderError as exc:
        failure = exc.to_dict()
    except Exception:  # unexpected: log the detail, show the user something readable
        logger.exception("chat turn failed", extra={"conversation_id": conversation.id})
        failure = {
            "kind": "internal_error",
            "message": "GAIA hit an unexpected problem while generating a response.",
            "remedy": "The details were written to the log. Try again, or switch model.",
            "status": None,
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    assistant.content = "".join(chunks)
    assistant.latency_ms = latency_ms

    if failure is not None:
        assistant.status = "error" if not chunks else "stopped"
        assistant.error = failure.get("message")
        conversation.last_message_at = utcnow()
        _fail_task(session, task, failure.get("message") or "unknown error")
        session.commit()
        yield _sse("error", failure)
        return

    assistant.status = "complete"
    if usage is not None:
        assistant.input_tokens = usage.input_tokens
        assistant.output_tokens = usage.output_tokens
        models = await provider.list_models()
        assistant.cost_usd = provider.estimate_cost_usd(model_id, usage, models)

    conversation.last_message_at = utcnow()
    conversation.provider_id = provider.id
    conversation.model_id = model_id
    task.status = "succeeded"
    task.progress = 1.0
    task.finished_at = utcnow()
    session.commit()

    logger.info(
        "chat turn complete",
        extra={
            "session_id": uuid.uuid4().hex,
            "task_id": task.id,
            "tool": "llm",
            "status": "succeeded",
            "duration_ms": latency_ms,
            "provider": provider.id,
            "model": model_id,
        },
    )

    yield _sse(
        "done",
        {
            "message_id": assistant.id,
            "stop_reason": stop_reason,
            "latency_ms": latency_ms,
            "input_tokens": assistant.input_tokens,
            "output_tokens": assistant.output_tokens,
            "cost_usd": assistant.cost_usd,
        },
    )


def _fail_task(session: Session, task: TaskRun, error: str) -> None:
    task.status = "failed"
    task.error = error
    task.finished_at = utcnow()
    session.commit()
