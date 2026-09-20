"""faster-whisper STT — local, CPU, no cloud dependency.

Chosen over plain `openai-whisper` for Milestone 3's first slice: faster-whisper
runs on CTranslate2 rather than PyTorch, which means no torch install (a very
large dependency this project has otherwise avoided entirely) and meaningfully
faster CPU inference. Confirmed installing cleanly with prebuilt Windows wheels
on this machine's Python version before being adopted — not assumed.

Model: `tiny.en` by default (~75 MB on disk, downloaded once via
`huggingface_hub` and cached under the user's HF cache directory — not GAIA's
own data directory, disclosed in docs/PRIVACY.md). Chosen over `base`/`small`
for this first pass: smallest footprint, fastest load (~3s once cached vs.
~10s+ for base), lowest RAM/CPU floor, and accuracy confirmed adequate at
`beam_size=5` in manual testing — see docs/ARCHITECTURE.md, "Voice", for the
comparison this was picked from. `base.en`/`small.en` are drop-in upgrades:
change `_MODEL_SIZE` (or, once exposed, a setting) with no code changes
elsewhere, which is the entire point of this being a swappable provider.

The model is loaded once per process (class-level cache) and reused — first
call after a cold start pays the load cost, every call after that doesn't.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from gaia.voice.base import (
    HealthState,
    ProviderHealth,
    STTProvider,
    TranscriptionResult,
    VoiceNotConfigured,
    VoiceUnavailable,
)

_MODEL_SIZE = "tiny.en"
_BEAM_SIZE = 5
#: Generous headroom for a first-run model download/load plus transcription;
#: a bounded push-to-talk clip should never legitimately take this long.
_TIMEOUT_SECONDS = 120


class FasterWhisperSTT(STTProvider):
    id = "faster_whisper"
    display_name = "faster-whisper (local)"
    is_local = True
    requires_api_key = False

    _model: Any = None  # class-level: one model instance per process, not per call

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            from faster_whisper import WhisperModel

            cls._model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
        return cls._model

    async def health(self) -> ProviderHealth:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return ProviderHealth(HealthState.NOT_CONFIGURED, "faster-whisper is not installed.")
        return ProviderHealth(
            HealthState.OK, f"Model: {_MODEL_SIZE} (loads on first use, cached after)."
        )

    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, audio_path), timeout=_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            raise VoiceUnavailable(
                f"Transcription did not finish within {_TIMEOUT_SECONDS}s."
            ) from exc
        except VoiceNotConfigured:
            raise
        except VoiceUnavailable:
            raise
        except Exception as exc:  # backstop — must never raise past here
            raise VoiceUnavailable(f"Transcription failed: {exc}") from exc

    def _transcribe_sync(self, audio_path: str) -> TranscriptionResult:
        model = self._get_model()
        started = time.perf_counter()
        segments, info = model.transcribe(audio_path, beam_size=_BEAM_SIZE)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        duration = time.perf_counter() - started
        return TranscriptionResult(
            text=text, language=info.language, duration_s=round(duration, 3)
        )
