"""Voice provider unit tests. Real engines, not mocked — the point of these
tests is confirming the actual local STT/TTS engines produce real output on
this machine, not exercising a mock of them."""

from __future__ import annotations

import pytest

from gaia.voice.base import HealthState, VoiceNotConfigured, VoiceUnavailable
from gaia.voice.registry import build_stt_provider, build_tts_provider
from gaia.voice.stt_faster_whisper import FasterWhisperSTT
from gaia.voice.tts_pyttsx3 import Pyttsx3TTS

# --------------------------------------------------------------- TTS


async def test_tts_health_reports_ok():
    health = await Pyttsx3TTS().health()
    assert health.state == HealthState.OK


async def test_tts_synthesizes_real_audio(tmp_path):
    out = tmp_path / "out.wav"
    result = await Pyttsx3TTS().synthesize("Testing one two three.", out_path=str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    assert result.audio_path == str(out)
    assert result.duration_s is not None


async def test_tts_failure_on_unwritable_path_is_reported_not_raised(tmp_path):
    bad_path = tmp_path / "no_such_directory" / "out.wav"
    with pytest.raises(VoiceUnavailable):
        await Pyttsx3TTS().synthesize("hello", out_path=str(bad_path))


async def test_tts_rejects_nothing_for_whitespace_but_produces_something_or_fails_cleanly(tmp_path):
    # pyttsx3 itself has no concept of "empty text" validation — that guard
    # lives at the API layer (SpeakRequest's min_length). At the provider
    # level, prove only that whitespace-only input never raises past here.
    out = tmp_path / "out.wav"
    try:
        await Pyttsx3TTS().synthesize("   ", out_path=str(out))
    except VoiceUnavailable:
        pass  # also an acceptable outcome — either way, not an unhandled exception


# --------------------------------------------------------------- STT


async def test_stt_health_reports_ok():
    health = await FasterWhisperSTT().health()
    assert health.state == HealthState.OK


async def test_stt_transcribes_real_speech(tmp_path):
    # Round-trip through the TTS provider already proven above, rather than
    # committing a binary audio fixture to the repo.
    wav = tmp_path / "speech.wav"
    await Pyttsx3TTS().synthesize("Please list the files in my workspace.", out_path=str(wav))

    result = await FasterWhisperSTT().transcribe(str(wav))
    assert result.text.strip() != ""
    assert result.language == "en"


async def test_stt_reports_failure_on_invalid_audio_without_raising(tmp_path):
    garbage = tmp_path / "not_audio.wav"
    garbage.write_bytes(b"this is not a real audio file, just text pretending to be one")
    with pytest.raises(VoiceUnavailable):
        await FasterWhisperSTT().transcribe(str(garbage))


async def test_stt_reports_failure_on_missing_file():
    with pytest.raises(VoiceUnavailable):
        await FasterWhisperSTT().transcribe("C:/definitely/does-not-exist.wav")


async def test_stt_reports_empty_audio_without_raising(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    with pytest.raises(VoiceUnavailable):
        await FasterWhisperSTT().transcribe(str(empty))


# --------------------------------------------------------------- registry


def test_registry_builds_known_providers():
    assert isinstance(build_stt_provider("faster_whisper"), FasterWhisperSTT)
    assert isinstance(build_tts_provider("pyttsx3"), Pyttsx3TTS)


def test_registry_rejects_unknown_stt_provider():
    with pytest.raises(VoiceNotConfigured):
        build_stt_provider("does-not-exist")


def test_registry_rejects_unknown_tts_provider():
    with pytest.raises(VoiceNotConfigured):
        build_tts_provider("does-not-exist")


def test_registry_rejects_none_provider_id():
    with pytest.raises(VoiceNotConfigured):
        build_stt_provider(None)
