from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from gaia.services import conversation_service

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    q: str | None = Query(default=None, description="Search titles and message text"),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ConversationOut]:
    conversations = conversation_service.list_conversations(
        session, query=q, include_archived=include_archived, limit=limit, offset=offset
    )
    counts = conversation_service.message_counts(session, [c.id for c in conversations])
    result = []
    for conversation in conversations:
        item = ConversationOut.model_validate(conversation)
        item.message_count = counts.get(conversation.id, 0)
        result.append(item)
    return result


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate, session: Session = Depends(get_session)
) -> ConversationOut:
    conversation = conversation_service.create_conversation(
        session,
        title=payload.title,
        provider_id=payload.provider_id,
        model_id=payload.model_id,
    )
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: str, session: Session = Depends(get_session)
) -> ConversationDetail:
    conversation = conversation_service.get_conversation_with_messages(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    detail = ConversationDetail.model_validate(conversation)
    detail.messages = [MessageOut.model_validate(m) for m in conversation.messages]
    detail.message_count = len(detail.messages)
    return detail


@router.patch("/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    session: Session = Depends(get_session),
) -> ConversationOut:
    conversation = conversation_service.get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # `exclude_unset` matters: it is what lets a client clear `pinned` to False
    # without every other field being reset to its default.
    conversation_service.update_conversation(
        session, conversation, **payload.model_dump(exclude_unset=True)
    )
    return ConversationOut.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, session: Session = Depends(get_session)) -> None:
    if not conversation_service.delete_conversation(session, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: str, session: Session = Depends(get_session)
) -> list[MessageOut]:
    if conversation_service.get_conversation(session, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return [
        MessageOut.model_validate(m)
        for m in conversation_service.get_messages(session, conversation_id)
    ]
