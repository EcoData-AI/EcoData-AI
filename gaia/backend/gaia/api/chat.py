from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import ChatRequest, ToolConfirmationResolve
from gaia.services import tool_confirmation
from gaia.services.chat_service import TurnRequest, stream_turn

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(payload: ChatRequest, session: Session = Depends(get_session)) -> StreamingResponse:
    """Stream one assistant turn as Server-Sent Events.

    Event names: `user_message`, `start`, `delta`, `tool_call`,
    `tool_confirm_required`, `tool_result`, `error`, `done`. Errors are
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


@router.post("/chat/tool-confirmations/{call_id}", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_tool_confirmation(call_id: str, payload: ToolConfirmationResolve) -> None:
    """Resolve a CONFIRM-risk tool call raised mid-turn by `tool_confirm_required`.

    No tool ships in this milestone at a risk level above SAFE, so nothing
    calls this yet — it exists so filesystem and terminal tools (Milestone 2's
    later steps) need no further wiring here when they arrive.
    """
    resolved = await tool_confirmation.resolve(call_id, payload.approved)
    if not resolved:
        raise HTTPException(
            status_code=404, detail="No pending confirmation for that id (it may have timed out)."
        )
