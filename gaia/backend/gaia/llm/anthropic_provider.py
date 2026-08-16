"""Anthropic provider, built on the official `anthropic` SDK."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Sequence

import anthropic

from gaia.llm.base import (
    ChatMessage,
    HealthState,
    LLMProvider,
    ModelInfo,
    ProviderAuthError,
    ProviderConfig,
    ProviderHealth,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
    StreamEvent,
    ToolCallRequest,
    Usage,
)
from gaia.llm.catalog import ANTHROPIC_MODELS, DEFAULT_ANTHROPIC_MODEL, anthropic_capabilities


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    display_name = "Anthropic (Claude)"
    is_local = False
    requires_api_key = True
    setup_url = "https://console.anthropic.com/settings/keys"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self.config.api_key:
            raise ProviderNotConfigured(
                "No Anthropic API key is configured.",
                remedy="Add a key in Settings → Models, or set ANTHROPIC_API_KEY.",
            )
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(
                api_key=self.config.api_key,
                base_url=self.config.base_url or None,
                max_retries=2,
            )
        return self._client

    async def list_models(self) -> list[ModelInfo]:
        return list(ANTHROPIC_MODELS)

    async def health(self) -> ProviderHealth:
        if not self.config.api_key:
            return ProviderHealth(
                HealthState.NOT_CONFIGURED, "No API key configured for Anthropic."
            )
        started = time.perf_counter()
        try:
            client = self._get_client()
            # Cheapest possible authenticated call.
            await client.models.list(limit=1)
        except anthropic.AuthenticationError:
            return ProviderHealth(HealthState.ERROR, "The API key was rejected.")
        except anthropic.APIConnectionError as exc:
            return ProviderHealth(HealthState.ERROR, f"Could not reach the API: {exc}")
        except Exception as exc:  # health checks must never raise
            return ProviderHealth(HealthState.ERROR, str(exc))
        latency = int((time.perf_counter() - started) * 1000)
        return ProviderHealth(HealthState.OK, "Connected.", latency_ms=latency)

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
        client = self._get_client()
        caps = anthropic_capabilities(model)

        payload: dict[str, object] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _wire_messages(messages),
        }
        if system:
            payload["system"] = system
        # The Claude 5-series and Opus 4.7/4.8 reject sampling parameters with a
        # 400; only send temperature where the model still accepts it.
        if caps["supports_temperature"]:
            payload["temperature"] = temperature
        if caps["supports_effort"] and self.config.options.get("effort"):
            payload["output_config"] = {"effort": self.config.options["effort"]}
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]

        try:
            async with client.messages.stream(**payload) as stream:  # type: ignore[arg-type]
                async for text in stream.text_stream:
                    yield StreamEvent(type="text", text=text)
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError(
                "Anthropic rejected the API key.",
                remedy="Check the key in Settings → Models.",
                status=401,
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimited(
                "Anthropic rate limit reached.",
                remedy="Wait a moment and try again, or switch model in Settings.",
                status=429,
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderUnavailable(
                "Could not reach the Anthropic API.",
                remedy="Check your internet connection, then retry.",
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailable(
                f"Anthropic returned an error: {exc.message}",
                status=exc.status_code,
            ) from exc

        # A safety classifier can decline the request. That arrives as a normal
        # 200 with stop_reason "refusal" and little or no content, so it has to
        # be reported rather than silently rendered as an empty reply.
        if final.stop_reason == "refusal":
            yield StreamEvent(
                type="error",
                error={
                    "kind": "refused",
                    "message": "The model declined to answer this request.",
                    "remedy": "Try rephrasing, or switch to a different model in Settings.",
                    "status": None,
                },
            )
            return

        if final.stop_reason == "tool_use":
            calls = [
                ToolCallRequest(id=block.id, name=block.name, arguments=block.input)
                for block in final.content
                if block.type == "tool_use"
            ]
            if calls:
                yield StreamEvent(type="tool_use", tool_calls=calls)

        yield StreamEvent(
            type="usage",
            usage=Usage(
                input_tokens=final.usage.input_tokens,
                output_tokens=final.usage.output_tokens,
            ),
        )
        yield StreamEvent(type="done", stop_reason=final.stop_reason)

    async def resolve_model(self, requested: str | None) -> str:
        return requested or self.config.default_model or DEFAULT_ANTHROPIC_MODEL


def _wire_messages(messages: Sequence[ChatMessage]) -> list[dict[str, object]]:
    """Translate GAIA's neutral message shape into Anthropic content blocks.

    An assistant message that called tools becomes a `tool_use` content block;
    the tool's result comes back as a `user` message carrying a `tool_result`
    block — Anthropic has no separate "tool" role. Plain messages pass through
    unchanged via `ChatMessage.to_dict()`.
    """
    wire: list[dict[str, object]] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, object]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                for call in message.tool_calls
            )
            wire.append({"role": "assistant", "content": blocks})
        elif message.role == "tool":
            wire.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content,
                        }
                    ],
                }
            )
        else:
            wire.append(message.to_dict())
    return wire
