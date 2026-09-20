"""Voice API endpoints: real synthesis/transcription through the HTTP layer,
plus the audio-lifecycle guarantee — nothing left behind in `voice_dir` after
a request, success or failure."""

from __future__ import annotations

from gaia.config import get_settings


def _voice_dir_contents() -> list[str]:
    return [p.name for p in get_settings().voice_dir.glob("*")]


def test_speak_returns_real_audio(client, gaia_env):
    response = client.post("/api/voice/speak", json={"text": "Hello from the test suite."})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 0


def test_speak_rejects_empty_text(client):
    response = client.post("/api/voice/speak", json={"text": ""})
    assert response.status_code == 422


def test_speak_leaves_no_audio_file_behind(client, gaia_env):
    client.post("/api/voice/speak", json={"text": "cleanup check"})
    assert _voice_dir_contents() == []


def test_transcribe_rejects_empty_file(client):
    response = client.post(
        "/api/voice/transcribe", files={"file": ("empty.wav", b"", "audio/wav")}
    )
    assert response.status_code == 422


def test_transcribe_rejects_invalid_audio(client):
    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("bad.wav", b"not real audio data at all", "audio/wav")},
    )
    assert response.status_code == 502


def test_transcribe_leaves_no_audio_file_behind_on_failure(client, gaia_env):
    client.post(
        "/api/voice/transcribe",
        files={"file": ("bad.wav", b"not real audio data at all", "audio/wav")},
    )
    assert _voice_dir_contents() == []


def test_transcribe_real_audio_round_trip(client, gaia_env):
    # Synthesize real speech via /speak, feed the resulting WAV bytes straight
    # into /transcribe — exercises both engines and the full HTTP contract
    # with nothing mocked.
    speak_response = client.post(
        "/api/voice/speak", json={"text": "The quick brown fox jumps over the lazy dog."}
    )
    assert speak_response.status_code == 200

    transcribe_response = client.post(
        "/api/voice/transcribe",
        files={"file": ("recording.wav", speak_response.content, "audio/wav")},
    )
    assert transcribe_response.status_code == 200
    body = transcribe_response.json()
    assert body["text"].strip() != ""
    assert body["language"] == "en"


def test_transcribe_leaves_no_audio_file_behind_on_success(client, gaia_env):
    speak_response = client.post("/api/voice/speak", json={"text": "cleanup check two"})
    client.post(
        "/api/voice/transcribe",
        files={"file": ("recording.wav", speak_response.content, "audio/wav")},
    )
    assert _voice_dir_contents() == []


def test_speak_rejects_missing_body(client):
    response = client.post("/api/voice/speak", json={})
    assert response.status_code == 422
