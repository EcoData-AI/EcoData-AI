from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    sequence: int
    status: str
    error: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    provider_id: str | None = None
    model_id: str | None = None
    system_prompt: str | None = None
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    message_count: int = 0


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str | None = None
    provider_id: str | None = None
    model_id: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    pinned: bool | None = None
    archived: bool | None = None
    system_prompt: str | None = None
    model_id: str | None = None
    provider_id: str | None = None


class ChatRequest(BaseModel):
    conversation_id: str
    content: str = Field(min_length=1, max_length=200_000)
    provider_id: str | None = None
    model_id: str | None = None


class ProviderOut(BaseModel):
    id: str
    display_name: str
    is_local: bool
    requires_api_key: bool
    setup_url: str | None = None
    configured: bool = False
    key_hint: str | None = None
    key_source: str | None = None
    base_url: str | None = None
    default_model: str | None = None


class ProviderCredentialIn(BaseModel):
    api_key: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    default_model: str | None = None


class ModelOut(BaseModel):
    id: str
    name: str
    provider_id: str
    context_window: int
    max_output_tokens: int
    supports_streaming: bool
    supports_vision: bool
    supports_tools: bool
    is_local: bool
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None


class SettingsOut(BaseModel):
    values: dict[str, Any]
    data_dir: str


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


class ComponentStatus(BaseModel):
    name: str
    state: Literal["ok", "disabled", "not_configured", "error", "not_built"]
    detail: str = ""


class SystemStatus(BaseModel):
    version: str
    components: list[ComponentStatus]
    data_dir: str
    active_provider: str | None = None
    active_model: str | None = None


class PrivacyRow(BaseModel):
    label: str
    location: Literal["LOCAL", "CLOUD", "EXTERNAL", "LOCAL / CLOUD", "NOT BUILT"]
    detail: str


class CapabilityOut(BaseModel):
    """Honest reporting of what is and is not implemented (spec §3 and §53)."""

    key: str
    label: str
    available: bool
    milestone: int
    detail: str
