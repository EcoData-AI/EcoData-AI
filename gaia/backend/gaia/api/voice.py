"""Voice endpoints — HTTP shape only, no engine logic here.

Deliberately outside the chat turn: `/transcribe` runs *before* a normal
`POST /api/chat` call (the transcribed text becomes an ordinary `content`
string — the chat pipeline cannot tell it apart from typing), and `/speak`
runs *after* one, on the already-persisted final assistant text. Neither
endpoint touches `chat_service.py`, `ToolCall`, or the SSE stream.

Every temporary audio file this module creates — incoming recordings and
synthesized speech alike — is deleted in a `finally` block before the
response is returned. Nothing here is meant to outlive its own request; see
`config.voice_dir`'s docstring and docs/PRIVACY.md, "Voice".
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from gaia.config import get_settings
from gaia.db.session import get_session
from gaia.schemas.api import SpeakRequest, TranscribeResponse
from gaia.services import settings_service
from gaia.voice.base import VoiceProviderError
from gaia.voice.registry import build_stt_provider, build_tts_provider

router = APIRouter(prefix="/api/voice", tags=["voice"])

#: Generous for a few minutes of push-to-talk audio; nowhere near unbounded.
_MAX_AUDIO_BYTES = 25 * 1024 * 1024


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    file: UploadFile, session: Session = Depends(get_session)
) -> TranscribeResponse:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=422, detail="The uploaded recording is empty.")
    if len(payload) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is too large.")

    settings = get_settings()
    settings.ensure_directories()
    # The extension doesn't need to match the browser's real codec exactly —
    # ffmpeg (via `av`, faster-whisper's decode path) sniffs the container
    # from its contents, not the filename.
    temp_path = settings.voice_dir / f"stt-{uuid.uuid4().hex}.audio"
    temp_path.write_bytes(payload)
    try:
        provider_id = settings_service.get(session, settings_service.STT_PROVIDER)
        provider = build_stt_provider(provider_id)
        result = await provider.transcribe(str(temp_path))
    except VoiceProviderError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    finally:
        # The raw recording is never kept beyond the single request that needed it.
        temp_path.unlink(missing_ok=True)

    if not result.text.strip():
        raise HTTPException(
            status_code=422, detail="Could not make out any speech in that recording."
        )
    return TranscribeResponse(text=result.text, language=result.language)


@router.post("/speak")
async def speak(payload: SpeakRequest, session: Session = Depends(get_session)) -> Response:
    settings = get_settings()
    settings.ensure_directories()
    out_path = settings.voice_dir / f"tts-{uuid.uuid4().hex}.wav"
    try:
        provider_id = settings_service.get(session, settings_service.TTS_PROVIDER)
        provider = build_tts_provider(provider_id)
        await provider.synthesize(payload.text, out_path=str(out_path))
        audio_bytes = out_path.read_bytes()
    except VoiceProviderError as exc:
        raise HTTPException(status_code=502, detail=exc.message) from exc
    finally:
        # The synthesized clip is read into the response body above and then
        # deleted here — nothing is kept on disk after this request returns.
        out_path.unlink(missing_ok=True)

    return Response(content=audio_bytes, media_type="audio/wav")
