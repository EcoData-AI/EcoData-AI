"""Provider-agnostic LLM interface.

GAIA never talks to a vendor SDK directly. Everything above this layer sees
`LLMProvider`, `ChatMessage` and `StreamEvent`, which means a provider can be
swapped from Settings at runtime without touching the chat pipeline.
"""

from __future__ import annotations

import abc
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]


class ProviderError(Exception):
    """Base class for provider failures surfaced to the user.

    Carries a plain-language `message` plus optional `remedy` so the UI can show
    something better than a stack trace (see §57 of the product spec).
    """

    kind = "provider_error"

    def __init__(self, message: str, *, remedy: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "remedy": self.remedy,
            "status": self.status,
        }


class ProviderNotConfigured(ProviderError):
    """The provider exists but is missing credentials or a reachable endpoint."""

    kind = "not_configured"


class ProviderUnavailable(ProviderError):
    """The provider is configured but the request could not be completed."""

    kind = "unavailable"


class ProviderAuthError(ProviderError):
    kind = "auth_error"


class ProviderRateLimited(ProviderError):
    kind = "rate_limited"


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class ModelInfo:
    id: str
    name: str
    provider_id: str
    context_window: int
    max_output_tokens: int = 4096
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_tools: bool = False
    is_local: bool = False
    # USD per million tokens. None means "unknown/not billed", which the UI
    # renders as "—" rather than inventing a number.
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider_id": self.provider_id,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "is_local": self.is_local,
            "input_cost_per_mtok": self.input_cost_per_mtok,
            "output_cost_per_mtok": self.output_cost_per_mtok,
        }


class HealthState(str, Enum):
    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


@dataclass(slots=True)
class ProviderHealth:
    state: HealthState
    detail: str = ""
    latency_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "detail": self.detail, "latency_ms": self.latency_ms}


@dataclass(slots=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass(slots=True)
class StreamEvent:
    """One item from a streaming completion.

    type:
      "text"   -> `text` holds the delta to append
      "usage"  -> `usage` holds token counts reported by the provider
      "done"   -> stream finished normally; `stop_reason` may be set
      "error"  -> `error` holds a serialisable ProviderError payload
    """

    type: Literal["text", "usage", "done", "error"]
    text: str = ""
    usage: Usage | None = None
    stop_reason: str | None = None
    error: dict[str, Any] | None = None


@dataclass(slots=True)
class ProviderConfig:
    """Everything a provider needs, resolved from settings + secret store."""

    api_key: str | None = None
    base_url: str | None = None
    default_model: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Contract every provider implements.

    Implementations must be safe to construct without network access; all I/O
    happens in `health()`, `list_models()` and `stream_chat()`.
    """

    #: stable identifier used in settings and the database
    id: str = "abstract"
    #: human-readable name shown in the UI
    display_name: str = "Abstract provider"
    #: True when inference happens on this machine (drives the privacy dashboard)
    is_local: bool = False
    #: whether an API key is required before the provider can be used
    requires_api_key: bool = True
    #: link shown in Settings when the user needs to obtain credentials
    setup_url: str | None = None

    def __init__(self, config: ProviderConfig):
        self.config = config

    # -- capability description -------------------------------------------

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Models this provider can serve right now."""

    @abc.abstractmethod
    async def health(self) -> ProviderHealth:
        """Cheap reachability/credential check. Must never raise."""

    # -- inference ---------------------------------------------------------

    @abc.abstractmethod
    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion.

        Implementations yield `StreamEvent`s and must translate transport and
        vendor errors into `ProviderError` subclasses rather than leaking
        httpx/JSON exceptions upward.
        """

    # -- helpers -----------------------------------------------------------

    def is_configured(self) -> bool:
        if not self.requires_api_key:
            return True
        return bool(self.config.api_key)

    async def resolve_model(self, requested: str | None) -> str:
        if requested:
            return requested
        if self.config.default_model:
            return self.config.default_model
        models = await self.list_models()
        if not models:
            raise ProviderNotConfigured(
                f"{self.display_name} has no models available.",
                remedy="Check the provider configuration in Settings → Models.",
            )
        return models[0].id

    def estimate_cost_usd(
        self, model_id: str, usage: Usage, models: list[ModelInfo]
    ) -> float | None:
        info = next((m for m in models if m.id == model_id), None)
        if info is None or info.input_cost_per_mtok is None or info.output_cost_per_mtok is None:
            return None
        if usage.input_tokens is None and usage.output_tokens is None:
            return None
        inp = (usage.input_tokens or 0) / 1_000_000 * info.input_cost_per_mtok
        out = (usage.output_tokens or 0) / 1_000_000 * info.output_cost_per_mtok
        return round(inp + out, 6)
