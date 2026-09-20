"""pyttsx3 TTS — local, zero model download, uses voices already on the OS.

Chosen over a neural engine (Piper, Coqui, ...) for Milestone 3's *first*
slice specifically because the milestone's own priority is reliability over
voice quality: pyttsx3 wraps the operating system's own speech engine
(SAPI5 on Windows, confirmed working here — NSSpeechSynthesizer on macOS,
espeak on Linux, untested on those platforms) so there is no model to
download, no extra runtime dependency beyond the small `pyttsx3`/`pywin32`
wheels, and no risk of a broken first run while a multi-hundred-MB voice
model fetches. A neural TTS provider (Piper is the natural next one — small,
local, ONNX-based, much better prosody) is a second `TTSProvider`
implementation away, not a rewrite — see `gaia/voice/base.py`.

pyttsx3 is not safe to keep a single shared engine instance across concurrent
async calls (it wraps stateful COM/OS speech APIs). Each call constructs its
own engine inside a worker thread and disposes of it before returning, rather
than caching one at class level the way `FasterWhisperSTT` caches its model.

**`engine.runAndWait()` can hang indefinitely rather than raise** — confirmed
empirically, not assumed: pointing it at an output path whose parent
directory doesn't exist blocks `runAndWait()` forever instead of failing,
because the "utterance finished" event pyttsx3 waits on never fires if the
underlying write never happened. Two independent guards against this: the
output directory is checked *before* the engine is ever touched, and the
whole call is wrapped in a hard wall-clock timeout as a backstop against any
other cause of the same failure mode — an `asyncio.to_thread` worker can't be
force-killed cleanly, so the timeout unblocks the caller even if the
underlying OS thread lingers, which is the best available guarantee here.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from gaia.voice.base import (
    HealthState,
    ProviderHealth,
    SynthesisResult,
    TTSProvider,
    VoiceUnavailable,
)

#: Substrings checked against a voice's id/name to prefer an English voice
#: when more than one is installed (this machine has both a French and an
#: English SAPI5 voice — silently picking the first one would be wrong more
#: often than not).
_PREFERRED_VOICE_HINTS = ("en_US", "en-US", "EN-US", "english")

#: Hard ceiling on one synthesis call. A few seconds of speech should take a
#: few seconds; this is generous headroom, not a target.
_TIMEOUT_SECONDS = 30


class Pyttsx3TTS(TTSProvider):
    id = "pyttsx3"
    display_name = "System voices (pyttsx3)"
    is_local = True
    requires_api_key = False

    async def health(self) -> ProviderHealth:
        try:
            import pyttsx3
        except ImportError:
            return ProviderHealth(HealthState.NOT_CONFIGURED, "pyttsx3 is not installed.")
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            engine.stop()
        except Exception as exc:
            return ProviderHealth(
                HealthState.ERROR, f"Could not reach the system speech engine: {exc}"
            )
        if not voices:
            return ProviderHealth(HealthState.ERROR, "No system voices are installed.")
        return ProviderHealth(HealthState.OK, f"{len(voices)} voice(s) available.")

    async def synthesize(self, text: str, *, out_path: str) -> SynthesisResult:
        # Checked up front, outside the worker thread: this is the one known
        # cause of runAndWait() hanging instead of raising (see module
        # docstring), so it must never reach the engine at all.
        if not Path(out_path).parent.is_dir():
            raise VoiceUnavailable(f"'{Path(out_path).parent}' does not exist.")

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._synthesize_sync, text, out_path),
                timeout=_TIMEOUT_SECONDS,
            )
        # asyncio.TimeoutError, not the bare builtin — correct on py3.10 too.
        except asyncio.TimeoutError as exc:
            raise VoiceUnavailable(
                f"Speech synthesis did not finish within {_TIMEOUT_SECONDS}s."
            ) from exc
        except VoiceUnavailable:
            raise
        except Exception as exc:  # backstop — must never raise past here
            raise VoiceUnavailable(f"Speech synthesis failed: {exc}") from exc

    def _synthesize_sync(self, text: str, out_path: str) -> SynthesisResult:
        import pyttsx3

        started = time.perf_counter()
        engine = pyttsx3.init()
        try:
            for voice in engine.getProperty("voices") or []:
                identifier = f"{voice.id} {getattr(voice, 'name', '')}".lower()
                if any(hint.lower() in identifier for hint in _PREFERRED_VOICE_HINTS):
                    engine.setProperty("voice", voice.id)
                    break
            engine.save_to_file(text, out_path)
            engine.runAndWait()
        finally:
            engine.stop()

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise VoiceUnavailable("The speech engine produced no audio output.")

        duration = time.perf_counter() - started
        return SynthesisResult(audio_path=out_path, duration_s=round(duration, 3))
