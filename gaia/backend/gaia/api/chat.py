from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import ChatRequest
from gaia.services.chat_service import TurnRequest, stream_turn

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(payload: ChatRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream one assistant turn as Server-Sent Events.

    Event names: `user_message`, `start`, `delta`, `error`, `done`. Errors are
    delivered as an SSE `error` event with a human-readable message rather than
    as an HTTP error status, because the stream may already have started by the
    time the failure occurs.
    """
    generator = stream_turn(
        session,
        TurnRequest(
            conversation_id=payload.conversation_id,
            content=payload.content,
            provider_id=payload.provider_id,
            model_id=payload.model_id,
        ),
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Disable proxy buffering so tokens are not held back.
            "X-Accel-Buffering": "no",
        },
    )
