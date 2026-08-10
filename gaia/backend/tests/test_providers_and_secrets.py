from __future__ import annotations

import pytest

from gaia.core import secrets
from gaia.llm.anthropic_provider import AnthropicProvider
from gaia.llm.base import ChatMessage, ProviderConfig, ProviderNotConfigured
from gaia.llm.catalog import ANTHROPIC_MODELS, anthropic_capabilities


def test_api_key_roundtrip_and_redaction(gaia_env):
    assert secrets.get_api_key("anthropic") is None
    assert secrets.describe_key("anthropic")["configured"] is False

    secrets.set_api_key("anthropic", "sk-ant-test-abcd1234")

    assert secrets.get_api_key("anthropic") == "sk-ant-test-abcd1234"
    described = secrets.describe_key("anthropic")
    assert described["configured"] is True
    # Only the last four characters may be exposed.
    assert described["hint"] == "…1234"
    assert "sk-ant" not in str(described)

    secrets.delete_api_key("anthropic")
    assert secrets.get_api_key("anthropic") is None


def test_environment_variable_takes_precedence(gaia_env, monkeypatch):
    secrets.set_api_key("anthropic", "from-store")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert secrets.get_api_key("anthropic") == "from-env"


def test_credentials_endpoint_never_echoes_the_key(client):
    response = client.put(
        "/api/providers/anthropic/credentials", json={"api_key": "sk-ant-secret-value"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["key_hint"] == "…alue"
    assert "sk-ant-secret-value" not in response.text


def test_provider_listing_and_unknown_provider(client):
    ids = {p["id"] for p in client.get("/api/providers").json()}
    assert {"anthropic", "openai_compatible", "ollama"} <= ids
    assert client.get("/api/providers/nonsense/models").status_code == 404


def test_anthropic_models_endpoint_returns_catalog(client):
    models = client.get("/api/providers/anthropic/models").json()
    ids = {m["id"] for m in models}
    assert "claude-opus-5" in ids
    opus = next(m for m in models if m["id"] == "claude-opus-5")
    assert opus["context_window"] == 1_000_000
    assert opus["input_cost_per_mtok"] == 5.0


def test_sampling_parameter_capability_flags():
    """The Claude 5-series rejects `temperature` with a 400 — never send it."""
    assert anthropic_capabilities("claude-opus-5")["supports_temperature"] is False
    assert anthropic_capabilities("claude-sonnet-5")["supports_temperature"] is False
    # Haiku 4.5 still accepts sampling params but rejects `effort`.
    assert anthropic_capabilities("claude-haiku-4-5")["supports_temperature"] is True
    assert anthropic_capabilities("claude-haiku-4-5")["supports_effort"] is False
    # An unrecognised (likely newer) model defaults to the safe direction.
    assert anthropic_capabilities("claude-future-9")["supports_temperature"] is False


def test_every_catalog_model_has_capability_flags():
    for model in ANTHROPIC_MODELS:
        caps = anthropic_capabilities(model.id)
        assert set(caps) == {"supports_effort", "supports_temperature"}


async def test_unconfigured_anthropic_provider_raises_not_configured():
    provider = AnthropicProvider(ProviderConfig(api_key=None))
    assert provider.is_configured() is False
    health = await provider.health()
    assert health.state.value == "not_configured"

    with pytest.raises(ProviderNotConfigured):
        async for _ in provider.stream_chat(
            [ChatMessage(role="user", content="hi")], model="claude-opus-5"
        ):
            pass


async def test_cost_estimate_uses_catalog_pricing():
    from gaia.llm.base import Usage

    provider = AnthropicProvider(ProviderConfig(api_key="x"))
    models = await provider.list_models()
    cost = provider.estimate_cost_usd(
        "claude-opus-5", Usage(input_tokens=1_000_000, output_tokens=1_000_000), models
    )
    assert cost == pytest.approx(30.0)  # $5 in + $25 out

    assert provider.estimate_cost_usd("unknown-model", Usage(1, 1), models) is None
