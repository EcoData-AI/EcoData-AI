"""The chat turn: context → provider → (tool loop) → persist.

Emits Server-Sent Events so the UI can render tokens as they arrive. The
assistant message row is created *before* streaming starts with status
"streaming", then filled in as text arrives. That means an interrupted turn
leaves a visible partial message with an honest status rather than vanishing.

Milestone 2 adds a bounded tool-call loop: if the model requests a tool, GAIA
executes it (or pauses for confirmation, for a CONFIRM-risk tool), feeds the
result back, and calls the provider again — up to `MAX_TOOL_ITERATIONS` times
per turn. Only the final assistant text is ever persisted as a `Message`; the
tool round-trip itself lives in the `ToolCall` audit table and in
`Message.extra`, so `context_builder` and message history need no changes.

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
from gaia.db.models import Message, TaskRun, ToolCall
from gaia.llm.base import ChatMessage, LLMProvider, ProviderError, ToolCallRequest
from gaia.llm.registry import build_provider
from gaia.services import conversation_service, settings_service, tool_confirmation
from gaia.tools.base import RiskLevel, ToolResult
from gaia.tools.registry import get_tool, tool_specs_for_provider

logger = logging.getLogger("gaia.chat")

#: At most this many provider round-trips per turn. A model that keeps
#: requesting tools forever (misbehaving, or stuck in a loop it can't resolve)
#: stops here rather than running away; the turn still completes, honestly,
#: with whatever text has been produced so far.
MAX_TOOL_ITERATIONS = 6


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


async def _execute_tool(tool_name: str, arguments: dict) -> ToolResult:
    """Run a tool, timed, with a backstop so a buggy tool can never crash the turn.

    `Tool.execute` is documented to never raise, but this is the last line of
    defence if one does anyway — the same posture `stream_chat`'s caller
    already takes with provider exceptions.
    """
    tool = get_tool(tool_name)
    if tool is None:
        return ToolResult(ok=False, content="", error="That tool is not available.")
    try:
        return await tool.execute(arguments)
    except Exception as exc:  # noqa: BLE001 - deliberate backstop, see docstring
        logger.exception("tool execution failed", extra={"tool": tool_name})
        return ToolResult(ok=False, content="", error=f"The tool raised an unexpected error: {exc}")


async def _run_tool_calls(
    session: Session,
    conversation,
    assistant: Message,
    task: TaskRun,
    requests: list[ToolCallRequest],
    working_messages: list[ChatMessage],
    tool_call_log: list[dict],
) -> AsyncIterator[str]:
    """Gate, execute, and audit each requested tool call; yield SSE events.

    Appends the resulting `role="tool"` message onto `working_messages` (in
    place) so the next provider call sees the answer, and appends a summary
    dict onto `tool_call_log` (in place) for `Message.extra`.
    """
    for call in requests:
        tool = get_tool(call.name)
        risk_level = tool.risk_level.value if tool is not None else RiskLevel.BLOCKED.value

        row = ToolCall(
            conversation_id=conversation.id,
            message_id=assistant.id,
            task_id=task.id,
            tool_name=call.name,
            risk_level=risk_level,
            arguments=call.arguments,
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        yield _sse(
            "tool_call",
            {
                "call_id": row.id,
                "tool": call.name,
                "arguments": call.arguments,
                "risk_level": risk_level,
            },
        )

        if tool is None:
            approval = "auto"
            result = ToolResult(ok=False, content="", error="That tool is not available.")
        elif tool.risk_level is RiskLevel.CONFIRM:
            yield _sse(
                "tool_confirm_required",
                {"call_id": row.id, "tool": call.name, "arguments": call.arguments},
            )
            approved = await tool_confirmation.wait_for_decision(row.id)
            if not approved:
                approval = "denied"
                result = ToolResult(ok=False, content="", error="The user denied this tool call.")
            else:
                approval = "approved"
                row.status = "running"
                session.commit()
                started = time.perf_counter()
                result = await _execute_tool(call.name, call.arguments)
                row.duration_ms = int((time.perf_counter() - started) * 1000)
        else:  # SAFE — BLOCKED tools never reach here; they were filtered out
            approval = "auto"  # of `tool_specs_for_provider()`, so no model asks for one.
            row.status = "running"
            session.commit()
            started = time.perf_counter()
            result = await _execute_tool(call.name, call.arguments)
            row.duration_ms = int((time.perf_counter() - started) * 1000)

        row.approval = approval
        row.status = "succeeded" if result.ok else "failed"
        row.result_summary = (result.content or result.error or "")[:500]
        row.error = None if result.ok else result.error
        session.commit()

        yield _sse(
            "tool_result",
            {
                "call_id": row.id,
                "tool": call.name,
                "ok": result.ok,
                "content": result.content,
                "display": result.display,
                "error": result.error,
            },
        )

        tool_call_log.append(
            {
                "call_id": row.id,
                "tool": call.name,
                "ok": result.ok,
                "content": result.content,
                "display": result.display,
                "error": result.error,
                "arguments": call.arguments,
            }
        )
        working_messages.append(
            ChatMessage(
                role="tool",
                content=result.content if result.ok else (result.error or "The tool failed."),
                tool_call_id=call.id,
            )
        )


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

    tool_specs = tool_specs_for_provider()
    working_messages: list[ChatMessage] = list(context.messages)
    tool_call_log: list[dict] = []

    started = time.perf_counter()
    final_chunks: list[str] = []
    usage = None
    stop_reason = None
    failure: dict | None = None
    hit_iteration_cap = False

    for _iteration in range(MAX_TOOL_ITERATIONS):
        iteration_chunks: list[str] = []
        tool_requests: list[ToolCallRequest] = []

        try:
            temperature = float(settings_service.get(session, settings_service.TEMPERATURE) or 0.7)
            max_tokens = int(settings_service.get(session, settings_service.MAX_TOKENS) or 16000)
            stream = provider.stream_chat(
                working_messages,
                model=model_id,
                system=context.system,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tool_specs,
            )
            async for event in stream:
                if event.type == "text":
                    iteration_chunks.append(event.text)
                    yield _sse("delta", {"text": event.text})
                elif event.type == "tool_use":
                    tool_requests.extend(event.tool_calls or [])
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

        final_chunks.extend(iteration_chunks)

        if failure is not None:
            break

        if not tool_requests:
            break  # a normal answer, with no further tool calls requested

        working_messages.append(
            ChatMessage(
                role="assistant", content="".join(iteration_chunks), tool_calls=tool_requests
            )
        )
        async for frame in _run_tool_calls(
            session, conversation, assistant, task, tool_requests, working_messages, tool_call_log
        ):
            yield frame
    else:
        # The loop ran MAX_TOOL_ITERATIONS times and always found another tool
        # request — stop asking rather than looping indefinitely.
        hit_iteration_cap = True

    latency_ms = int((time.perf_counter() - started) * 1000)
    assistant.content = "".join(final_chunks)
    if hit_iteration_cap:
        assistant.content += (
            "\n\n_[GAIA stopped calling tools after reaching this turn's limit of "
            f"{MAX_TOOL_ITERATIONS} tool calls.]_"
        )
    assistant.latency_ms = latency_ms
    if tool_call_log:
        assistant.extra = {"tool_calls": tool_call_log}

    if failure is not None:
        assistant.status = "error" if not final_chunks else "stopped"
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
            "tool_calls": len(tool_call_log),
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
