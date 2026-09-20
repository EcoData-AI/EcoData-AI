"""Provider-agnostic voice interface.

Mirrors `gaia.llm.base` on purpose: GAIA never talks to a speech engine
directly outside this layer, so an engine can be swapped from Settings later
without touching `api/voice.py` or anything upstream of it — the same
guarantee `LLMProvider` already gives for chat providers.

This is a **peer** of `gaia.llm`, not a dependent of it. Voice is not a chat
provider and not a tool: STT/TTS never see a conversation, never call the
model, and are never invoked by the model as a tool call. They sit entirely
outside the chat turn — STT produces plain text *before* a normal
`POST /api/chat` call; TTS consumes the already-persisted final assistant
text *after* the turn's `done` event. `chat_service.py` has no idea voice
exists, and that is deliberate: see docs/ARCHITECTURE.md, "Voice".
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from typing import Any


class VoiceProviderError(Exception):
    """Base class for STT/TTS failures surfaced to the user.

    Carries a plain-language `message`, same posture as `llm.base.ProviderError`
    — nothing above this layer should ever see a raw engine exception.
    """

    kind = "voice_provider_error"

    def __init__(self, message: str, *, remedy: str | None = None):
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": self.message, "remedy": self.remedy}


class VoiceNotConfigured(VoiceProviderError):
    """The requested engine id is unknown, or its dependency isn't installed."""

    kind = "not_configured"


class VoiceUnavailable(VoiceProviderError):
    """The engine is installed but the request could not be completed."""

    kind = "unavailable"


class HealthState(str, Enum):
    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


@dataclass(slots=True)
class ProviderHealth:
    state: HealthState
    detail: str = ""


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    duration_s: float | None = None


@dataclass(slots=True)
class SynthesisResult:
    audio_path: str
    duration_s: float | None = None
    mime_type: str = "audio/wav"


class STTProvider(abc.ABC):
    """Speech-to-text. Implementations must be safe to construct with no
    arguments; all I/O and computation happens in `transcribe()`."""

    id: str = "abstract"
    display_name: str = "Abstract STT provider"
    is_local: bool = True
    requires_api_key: bool = False

    @abc.abstractmethod
    async def health(self) -> ProviderHealth:
        """Cheap availability check. Must never raise."""

    @abc.abstractmethod
    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        """Transcribe the audio file at `audio_path`.

        Must translate engine failures into `VoiceProviderError` subclasses
        rather than leaking a raw exception — the same rule `LLMProvider`
        implementations already follow for vendor/transport errors.
        """


class TTSProvider(abc.ABC):
    """Text-to-speech. Implementations must be safe to construct with no
    arguments; all I/O and computation happens in `synthesize()`."""

    id: str = "abstract"
    display_name: str = "Abstract TTS provider"
    is_local: bool = True
    requires_api_key: bool = False

    @abc.abstractmethod
    async def health(self) -> ProviderHealth:
        """Cheap availability check. Must never raise."""

    @abc.abstractmethod
    async def synthesize(self, text: str, *, out_path: str) -> SynthesisResult:
        """Synthesize `text` to a WAV file at `out_path`.

        Must translate engine failures into `VoiceProviderError` subclasses
        rather than leaking a raw exception.
        """
