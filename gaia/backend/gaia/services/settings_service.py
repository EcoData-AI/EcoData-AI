"""Application settings stored in the database.

Secrets are explicitly out of scope here — see `gaia.core.secrets`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.models import Setting

# Keys are namespaced so a future settings page can enumerate a section.
ACTIVE_PROVIDER = "llm.active_provider"
ACTIVE_MODEL = "llm.active_model"
CUSTOM_INSTRUCTIONS = "general.custom_instructions"
TEMPERATURE = "llm.temperature"
MAX_TOKENS = "llm.max_tokens"
THEME = "appearance.theme"
ONBOARDING_COMPLETE = "general.onboarding_complete"
COST_LIMIT_USD = "llm.monthly_cost_limit_usd"

DEFAULTS: dict[str, Any] = {
    ACTIVE_PROVIDER: "anthropic",
    ACTIVE_MODEL: None,
    CUSTOM_INSTRUCTIONS: "",
    TEMPERATURE: 0.7,
    MAX_TOKENS: 16000,
    THEME: "system",
    ONBOARDING_COMPLETE: False,
    COST_LIMIT_USD: None,
}

#: Per-provider configuration lives under `provider.<id>` as a JSON blob.
PROVIDER_PREFIX = "provider."


def get(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return row.value


def set_value(session: Session, key: str, value: Any) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()


def all_settings(session: Session) -> dict[str, Any]:
    rows = session.execute(select(Setting)).scalars().all()
    stored = {row.key: row.value for row in rows}
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in stored.items() if not k.startswith(PROVIDER_PREFIX)})
    return merged


def get_active_provider_id(session: Session) -> str:
    return get(session, ACTIVE_PROVIDER) or DEFAULTS[ACTIVE_PROVIDER]


def get_provider_settings(session: Session, provider_id: str) -> dict[str, Any]:
    return get(session, f"{PROVIDER_PREFIX}{provider_id}", {}) or {}


def set_provider_settings(session: Session, provider_id: str, values: dict[str, Any]) -> None:
    current = get_provider_settings(session, provider_id)
    current.update({k: v for k, v in values.items() if v is not None})
    set_value(session, f"{PROVIDER_PREFIX}{provider_id}", current)
