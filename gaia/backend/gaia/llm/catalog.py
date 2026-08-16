"""Static capability catalogue for providers that do not advertise capabilities.

Two things here are load-bearing and easy to get wrong, so they are data rather
than scattered `if` statements:

* `supports_temperature` — the Claude 5-series and Opus 4.7/4.8 **reject**
  `temperature`/`top_p`/`top_k` with a 400. Sending one breaks the request.
* `supports_effort` — `output_config.effort` errors on Haiku 4.5.

Pricing is USD per million tokens, current as of 2026-06-24. It is only used for
the cost estimate shown in the UI; `None` renders as "—" rather than a guess.
"""

from __future__ import annotations

from gaia.llm.base import ModelInfo

ANTHROPIC_PROVIDER_ID = "anthropic"


def _model(
    model_id: str,
    name: str,
    *,
    context_window: int,
    max_output_tokens: int,
    input_cost: float | None,
    output_cost: float | None,
    supports_effort: bool = True,
    supports_temperature: bool = False,
) -> ModelInfo:
    info = ModelInfo(
        id=model_id,
        name=name,
        provider_id=ANTHROPIC_PROVIDER_ID,
        context_window=context_window,
        max_output_tokens=max_output_tokens,
        supports_streaming=True,
        supports_vision=True,
        supports_tools=True,
        is_local=False,
        input_cost_per_mtok=input_cost,
        output_cost_per_mtok=output_cost,
    )
    # Stashed as attributes rather than dataclass fields so ModelInfo stays a
    # provider-neutral shape; the Anthropic provider is the only reader.
    ANTHROPIC_CAPABILITIES[model_id] = {
        "supports_effort": supports_effort,
        "supports_temperature": supports_temperature,
    }
    return info


ANTHROPIC_CAPABILITIES: dict[str, dict[str, bool]] = {}

ANTHROPIC_MODELS: list[ModelInfo] = [
    _model(
        "claude-opus-5",
        "Claude Opus 5",
        context_window=1_000_000,
        max_output_tokens=64_000,
        input_cost=5.00,
        output_cost=25.00,
    ),
    _model(
        "claude-sonnet-5",
        "Claude Sonnet 5",
        context_window=1_000_000,
        max_output_tokens=64_000,
        input_cost=3.00,
        output_cost=15.00,
    ),
    _model(
        "claude-opus-4-8",
        "Claude Opus 4.8",
        context_window=1_000_000,
        max_output_tokens=64_000,
        input_cost=5.00,
        output_cost=25.00,
    ),
    _model(
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        context_window=200_000,
        max_output_tokens=32_000,
        input_cost=1.00,
        output_cost=5.00,
        # `output_config.effort` errors on Haiku 4.5.
        supports_effort=False,
        # Haiku 4.5 still accepts sampling parameters.
        supports_temperature=True,
    ),
]

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"


def anthropic_capabilities(model_id: str) -> dict[str, bool]:
    """Capabilities for a known model, or conservative defaults for unknown ones.

    An unknown id is most likely a model released after this catalogue was
    written. Assume the newer-model behaviour (no sampling params, effort
    supported), which is the safe direction: sending `temperature` to a model
    that rejects it is a hard 400, whereas omitting it always works.
    """
    return ANTHROPIC_CAPABILITIES.get(
        model_id, {"supports_effort": True, "supports_temperature": False}
    )
