"""Ollama provider — fully local inference, no API key, nothing leaves the machine."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Sequence

import httpx

from gaia.llm.base import (
    ChatMessage,
    HealthState,
    LLMProvider,
    ModelInfo,
    ProviderConfig,
    ProviderHealth,
    ProviderNotConfigured,
    ProviderUnavailable,
    StreamEvent,
    ToolCallRequest,
    Usage,
)

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaProvider(LLMProvider):
    id = "ollama"
    display_name = "Ollama (local)"
    is_local = True
    requires_api_key = False
    setup_url = "https://ollama.com/download"

    def __init__(self, config: ProviderConfig):
        super().__init__(config)

    @property
    def base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []
        models = []
        for entry in payload.get("models", []):
            name = entry.get("name")
            if not name:
                continue
            details = entry.get("details") or {}
            models.append(
                ModelInfo(
                    id=name,
                    name=name,
                    provider_id=self.id,
                    # Ollama does not report the context window here; the model
                    # file governs it. Reported as unknown rather than invented.
                    context_window=0,
                    max_output_tokens=4096,
                    supports_vision="clip" in str(details.get("families", "")).lower(),
                    is_local=True,
                    input_cost_per_mtok=0.0,
                    output_cost_per_mtok=0.0,
                )
            )
        models.sort(key=lambda m: m.id)
        return models

    async def health(self) -> ProviderHealth:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                count = len(response.json().get("models", []))
        except httpx.HTTPError:
            return ProviderHealth(
                HealthState.NOT_CONFIGURED,
                f"No Ollama server responding at {self.base_url}.",
            )
        except Exception as exc:
            return ProviderHealth(HealthState.ERROR, str(exc))
        if count == 0:
            return ProviderHealth(
                HealthState.ERROR,
                "Ollama is running but has no models installed. Run `ollama pull llama3.1`.",
            )
        return ProviderHealth(
            HealthState.OK,
            f"{count} local model(s) available.",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

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
        wire_messages: list[dict[str, object]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        wire_messages.extend(_wire_message(m) for m in messages)

        body: dict[str, object] = {
            "model": model,
            "messages": wire_messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10)) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/chat", json=body
                ) as response:
                    if response.status_code == 404:
                        raise ProviderNotConfigured(
                            f"Ollama does not have the model '{model}' installed.",
                            remedy=f"Run `ollama pull {model}` in a terminal, then retry.",
                            status=404,
                        )
                    if response.status_code >= 400:
                        raw = await response.aread()
                        raise ProviderUnavailable(
                            f"Ollama returned HTTP {response.status_code}: "
                            f"{raw.decode('utf-8', 'replace')[:300]}",
                            status=response.status_code,
                        )
                    async for event in _iter_ndjson(response):
                        yield event
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"Could not reach Ollama at {self.base_url}.",
                remedy="Start Ollama (`ollama serve`) and try again.",
            ) from exc


async def _iter_ndjson(response: httpx.Response) -> AsyncIterator[StreamEvent]:
    """Ollama streams newline-delimited JSON rather than SSE."""
    usage: Usage | None = None
    stop_reason: str | None = None
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = chunk.get("message") or {}
        if message.get("content"):
            yield StreamEvent(type="text", text=message["content"])
        # Ollama emits the full tool_calls list on one line rather than
        # streaming it incrementally, so this is a straight read, not an
        # accumulator like the OpenAI-compatible SSE path needs.
        if message.get("tool_calls"):
            calls = [
                ToolCallRequest(
                    id=uuid.uuid4().hex,
                    name=(call.get("function") or {}).get("name", ""),
                    arguments=(call.get("function") or {}).get("arguments") or {},
                )
                for call in message["tool_calls"]
            ]
            yield StreamEvent(type="tool_use", tool_calls=calls)
        if chunk.get("done"):
            stop_reason = chunk.get("done_reason") or "stop"
            usage = Usage(
                input_tokens=chunk.get("prompt_eval_count"),
                output_tokens=chunk.get("eval_count"),
            )
    if usage is not None:
        yield StreamEvent(type="usage", usage=usage)
    yield StreamEvent(type="done", stop_reason=stop_reason)


def _wire_message(message: ChatMessage) -> dict[str, object]:
    """Translate GAIA's neutral message shape into Ollama's wire format.

    Ollama's tool-call arguments are a parsed object, not a JSON string (unlike
    OpenAI's), so `ToolCallRequest.arguments` passes straight through.
    """
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {"function": {"name": call.name, "arguments": call.arguments}}
                for call in message.tool_calls
            ],
        }
    if message.role == "tool":
        return {"role": "tool", "content": message.content}
    return message.to_dict()
