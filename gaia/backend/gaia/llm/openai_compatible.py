"""Provider for any endpoint that speaks the OpenAI chat-completions protocol.

Covers OpenAI itself plus the many local and hosted servers that implement the
same wire format (LM Studio, vLLM, llama.cpp's server, OpenRouter, …). Only the
base URL changes, so GAIA treats them as one provider with a configurable
endpoint rather than shipping a class per vendor.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Sequence

import httpx

from gaia.llm.base import (
    ChatMessage,
    HealthState,
    LLMProvider,
    ModelInfo,
    ProviderAuthError,
    ProviderHealth,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderUnavailable,
    StreamEvent,
    Usage,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleProvider(LLMProvider):
    id = "openai_compatible"
    display_name = "OpenAI-compatible endpoint"
    is_local = False
    requires_api_key = True
    setup_url = "https://platform.openai.com/api-keys"

    @property
    def base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    async def list_models(self) -> list[ModelInfo]:
        """Ask the endpoint what it serves.

        Costs and context windows are not exposed by this protocol, so they are
        reported as unknown rather than guessed.
        """
        if not self.is_configured():
            return []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                response.raise_for_status()
                payload = response.json()
        except Exception:
            return []
        models = []
        for entry in payload.get("data", []):
            model_id = entry.get("id")
            if not model_id:
                continue
            models.append(
                ModelInfo(
                    id=model_id,
                    name=model_id,
                    provider_id=self.id,
                    context_window=0,  # unknown — the UI renders 0 as "—"
                    max_output_tokens=4096,
                    is_local="localhost" in self.base_url or "127.0.0.1" in self.base_url,
                )
            )
        models.sort(key=lambda m: m.id)
        return models

    async def health(self) -> ProviderHealth:
        if not self.is_configured():
            return ProviderHealth(HealthState.NOT_CONFIGURED, "No API key configured.")
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
            if response.status_code in (401, 403):
                return ProviderHealth(HealthState.ERROR, "The API key was rejected.")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderHealth(HealthState.ERROR, f"Could not reach {self.base_url}: {exc}")
        except Exception as exc:
            return ProviderHealth(HealthState.ERROR, str(exc))
        return ProviderHealth(
            HealthState.OK, "Connected.", latency_ms=int((time.perf_counter() - started) * 1000)
        )

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        if not self.is_configured():
            raise ProviderNotConfigured(
                f"{self.display_name} is not configured.",
                remedy="Add an API key and base URL in Settings → Models.",
            )

        wire_messages: list[dict[str, str]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})
        wire_messages.extend(m.to_dict() for m in messages)

        body = {
            "model": model,
            "messages": wire_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15)) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                ) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        raise _http_error(response.status_code, raw.decode("utf-8", "replace"))
                    async for event in _iter_sse(response):
                        yield event
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(
                f"Could not reach {self.base_url}.",
                remedy="Check that the endpoint is running and reachable.",
            ) from exc


async def _iter_sse(response: httpx.Response) -> AsyncIterator[StreamEvent]:
    usage: Usage | None = None
    stop_reason: str | None = None
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                yield StreamEvent(type="text", text=text)
            if choice.get("finish_reason"):
                stop_reason = choice["finish_reason"]
        if chunk.get("usage"):
            usage = Usage(
                input_tokens=chunk["usage"].get("prompt_tokens"),
                output_tokens=chunk["usage"].get("completion_tokens"),
            )
    if usage is not None:
        yield StreamEvent(type="usage", usage=usage)
    yield StreamEvent(type="done", stop_reason=stop_reason)


def _http_error(status: int, body: str) -> Exception:
    detail = body[:400]
    if status in (401, 403):
        return ProviderAuthError(
            "The endpoint rejected the API key.",
            remedy="Check the key in Settings → Models.",
            status=status,
        )
    if status == 429:
        return ProviderRateLimited(
            "Rate limit reached.", remedy="Wait a moment and try again.", status=status
        )
    return ProviderUnavailable(f"The endpoint returned HTTP {status}: {detail}", status=status)
