"""Provider registry — the single place that knows which providers exist."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from gaia.config import get_settings
from gaia.core import secrets
from gaia.llm.anthropic_provider import AnthropicProvider
from gaia.llm.base import LLMProvider, ProviderConfig, ProviderNotConfigured
from gaia.llm.mock_provider import MockProvider
from gaia.llm.ollama_provider import OllamaProvider
from gaia.llm.openai_compatible import OpenAICompatibleProvider
from gaia.services import settings_service

PROVIDER_CLASSES: dict[str, type[LLMProvider]] = {
    AnthropicProvider.id: AnthropicProvider,
    OpenAICompatibleProvider.id: OpenAICompatibleProvider,
    OllamaProvider.id: OllamaProvider,
    MockProvider.id: MockProvider,
}


def available_provider_ids() -> list[str]:
    """Providers the user may select. The mock is hidden unless explicitly enabled."""
    ids = [AnthropicProvider.id, OpenAICompatibleProvider.id, OllamaProvider.id]
    if get_settings().enable_mock_provider:
        ids.append(MockProvider.id)
    return ids


def describe_providers() -> list[dict[str, Any]]:
    return [
        {
            "id": cls.id,
            "display_name": cls.display_name,
            "is_local": cls.is_local,
            "requires_api_key": cls.requires_api_key,
            "setup_url": cls.setup_url,
        }
        for provider_id in available_provider_ids()
        if (cls := PROVIDER_CLASSES[provider_id])
    ]


def build_provider(session: Session, provider_id: str) -> LLMProvider:
    """Instantiate a provider using stored settings plus the secret store."""
    cls = PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        raise ProviderNotConfigured(
            f"Unknown provider '{provider_id}'.",
            remedy="Choose a provider in Settings → Models.",
        )
    provider_settings = settings_service.get_provider_settings(session, provider_id)
    config = ProviderConfig(
        api_key=secrets.get_api_key(provider_id) if cls.requires_api_key else None,
        base_url=provider_settings.get("base_url"),
        default_model=provider_settings.get("default_model"),
        options=provider_settings.get("options") or {},
    )
    return cls(config)


def build_active_provider(session: Session) -> LLMProvider:
    return build_provider(session, settings_service.get_active_provider_id(session))
