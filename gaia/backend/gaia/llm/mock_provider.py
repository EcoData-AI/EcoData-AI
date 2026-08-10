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
    Usage,
)

MOCK_MODEL_ID = "mock-echo"


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
    ) -> AsyncIterator[StreamEvent]:
        last_user = next(
            (m.content for m in reversed(list(messages)) if m.role == "user"),
            "",
        )
        reply = f"[mock provider] You said: {last_user}"
        for word in reply.split(" "):
            await asyncio.sleep(0)  # yield to the event loop, like a real stream
            yield StreamEvent(type="text", text=word + " ")
        yield StreamEvent(
            type="usage",
            usage=Usage(input_tokens=len(last_user.split()), output_tokens=len(reply.split())),
        )
        yield StreamEvent(type="done", stop_reason="end_turn")
