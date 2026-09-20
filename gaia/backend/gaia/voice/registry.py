"""Voice provider registry — the single place that knows which STT/TTS engines exist.

Mirrors `gaia.llm.registry` and `gaia.tools.registry` deliberately.
"""

from __future__ import annotations

from gaia.voice.base import STTProvider, TTSProvider, VoiceNotConfigured
from gaia.voice.stt_faster_whisper import FasterWhisperSTT
from gaia.voice.tts_pyttsx3 import Pyttsx3TTS

STT_CLASSES: dict[str, type[STTProvider]] = {
    FasterWhisperSTT.id: FasterWhisperSTT,
}

TTS_CLASSES: dict[str, type[TTSProvider]] = {
    Pyttsx3TTS.id: Pyttsx3TTS,
}


def describe_stt_providers() -> list[dict]:
    return [
        {"id": cls.id, "display_name": cls.display_name, "is_local": cls.is_local}
        for cls in STT_CLASSES.values()
    ]


def describe_tts_providers() -> list[dict]:
    return [
        {"id": cls.id, "display_name": cls.display_name, "is_local": cls.is_local}
        for cls in TTS_CLASSES.values()
    ]


def build_stt_provider(provider_id: str | None) -> STTProvider:
    cls = STT_CLASSES.get(provider_id or "")
    if cls is None:
        raise VoiceNotConfigured(
            f"Unknown STT provider '{provider_id}'.",
            remedy="Check Settings → Voice, or the voice.stt_provider setting.",
        )
    return cls()


def build_tts_provider(provider_id: str | None) -> TTSProvider:
    cls = TTS_CLASSES.get(provider_id or "")
    if cls is None:
        raise VoiceNotConfigured(
            f"Unknown TTS provider '{provider_id}'.",
            remedy="Check Settings → Voice, or the voice.tts_provider setting.",
        )
    return cls()
