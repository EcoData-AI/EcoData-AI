"""Deterministic stand-in used by the test-suite and CI.

This is **not a language model** and must never be presented as one. It echoes a
canned, clearly-labelled response so the streaming path, persistence and error
handling can be exercised without network access or credentials. It is hidden
from the UI unless `GAIA_ENABLE_MOCK_PROVIDER=1` is set.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

from gaia.llm.base import (
    ChatMessage,
    HealthState,
    LLMProvider,
    ModelInfo,
    ProviderHealth,
    StreamEvent,
    ToolCallRequest,
    Usage,
)

MOCK_MODEL_ID = "mock-echo"

#: A user message starting with this (case-insensitive) makes the mock provider
#: request the calculator tool with the rest of the text as the expression,
#: instead of echoing — this is what lets the tool-call loop be exercised
#: end-to-end in tests with no real provider or credentials.
CALC_TRIGGER = "calc:"

#: A user message starting with this always re-requests a tool call, even after
#: a tool result comes back — used to test the loop's iteration cap against a
#: model that never stops calling tools.
TOOLLOOP_TRIGGER = "toolloop:"


class MockProvider(LLMProvider):
    id = "mock"
    display_name = "Mock (testing only — not a real model)"
    is_local = True
    requires_api_key = False

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(
                id=MOCK_MODEL_ID,
                name="Mock echo (testing only)",
                provider_id=self.id,
                context_window=8192,
                max_output_tokens=1024,
                is_local=True,
                input_cost_per_mtok=0.0,
                output_cost_per_mtok=0.0,
            )
        ]

    async def health(self) -> ProviderHealth:
        return ProviderHealth(HealthState.OK, "Mock provider ready (not a language model).")

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, object]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        messages = list(messages)
        tool_result = next((m for m in reversed(messages) if m.role == "tool"), None)
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")

        # A model that never stops calling tools — exercises the iteration cap.
        has_toolloop_trigger = any(
            m.role == "user" and m.content.strip().lower().startswith(TOOLLOOP_TRIGGER)
            for m in messages
        )
        if tools and has_toolloop_trigger:
            call_id = f"mock-loop-{sum(1 for m in messages if m.role == 'tool') + 1}"
            yield StreamEvent(
                type="tool_use",
                tool_calls=[
                    ToolCallRequest(id=call_id, name="calculator", arguments={"expression": "1+1"})
                ],
            )
            yield StreamEvent(type="usage", usage=Usage(input_tokens=1, output_tokens=0))
            yield StreamEvent(type="done", stop_reason="tool_use")
            return

        # A tool result is present: acknowledge it instead of echoing again —
        # this is the loop's second (and later) provider call within one turn.
        if tool_result is not None:
            reply = f"[mock provider] tool result: {tool_result.content}"
            for word in reply.split(" "):
                await asyncio.sleep(0)
                yield StreamEvent(type="text", text=word + " ")
            yield StreamEvent(
                type="usage",
                usage=Usage(input_tokens=len(last_user.split()), output_tokens=len(reply.split())),
            )
            yield StreamEvent(type="done", stop_reason="end_turn")
            return

        if tools and last_user.strip().lower().startswith(CALC_TRIGGER):
            expression = last_user.split(":", 1)[1].strip()
            yield StreamEvent(
                type="tool_use",
                tool_calls=[
                    ToolCallRequest(
                        id="mock-call-1", name="calculator", arguments={"expression": expression}
                    )
                ],
            )
            yield StreamEvent(
                type="usage", usage=Usage(input_tokens=len(last_user.split()), output_tokens=0)
            )
            yield StreamEvent(type="done", stop_reason="tool_use")
            return

        reply = f"[mock provider] You said: {last_user}"
        for word in reply.split(" "):
            await asyncio.sleep(0)  # yield to the event loop, like a real stream
            yield StreamEvent(type="text", text=word + " ")
        yield StreamEvent(
            type="usage",
            usage=Usage(input_tokens=len(last_user.split()), output_tokens=len(reply.split())),
        )
        yield StreamEvent(type="done", stop_reason="end_turn")
