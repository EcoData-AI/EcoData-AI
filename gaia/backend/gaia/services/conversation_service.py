"""Conversation and message persistence."""

from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from gaia.db.base import utcnow
from gaia.db.models import Conversation, Message

DEFAULT_TITLE = "New conversation"


def create_conversation(
    session: Session,
    *,
    title: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Conversation:
    conversation = Conversation(
        title=(title or DEFAULT_TITLE).strip()[:300] or DEFAULT_TITLE,
        provider_id=provider_id,
        model_id=model_id,
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def get_conversation(session: Session, conversation_id: str) -> Conversation | None:
    return session.get(Conversation, conversation_id)


def get_conversation_with_messages(session: Session, conversation_id: str) -> Conversation | None:
    return session.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    ).scalar_one_or_none()


def list_conversations(
    session: Session,
    *,
    query: str | None = None,
    include_archived: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[Conversation]:
    stmt = select(Conversation)
    if not include_archived:
        stmt = stmt.where(Conversation.archived.is_(False))
    if query:
        pattern = f"%{query.strip()}%"
        # Search titles and message bodies; a conversation matches if either does.
        matching_ids = select(Message.conversation_id).where(Message.content.ilike(pattern))
        stmt = stmt.where(
            or_(Conversation.title.ilike(pattern), Conversation.id.in_(matching_ids))
        )
    stmt = stmt.order_by(
        Conversation.pinned.desc(),
        func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
    ).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def message_counts(session: Session, conversation_ids: list[str]) -> dict[str, int]:
    if not conversation_ids:
        return {}
    rows = session.execute(
        select(Message.conversation_id, func.count(Message.id))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    ).all()
    return {conversation_id: count for conversation_id, count in rows}


def update_conversation(session: Session, conversation: Conversation, **fields) -> Conversation:
    for key, value in fields.items():
        if value is not None and hasattr(conversation, key):
            setattr(conversation, key, value)
    session.commit()
    session.refresh(conversation)
    return conversation


def delete_conversation(session: Session, conversation_id: str) -> bool:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        return False
    session.delete(conversation)
    session.commit()
    return True


def next_sequence(session: Session, conversation_id: str) -> int:
    highest = session.execute(
        select(func.max(Message.sequence)).where(Message.conversation_id == conversation_id)
    ).scalar()
    return (highest or 0) + 1


def add_message(
    session: Session,
    conversation: Conversation,
    *,
    role: str,
    content: str,
    status: str = "complete",
    provider_id: str | None = None,
    model_id: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation.id,
        role=role,
        content=content,
        sequence=next_sequence(session, conversation.id),
        status=status,
        provider_id=provider_id,
        model_id=model_id,
    )
    session.add(message)
    conversation.last_message_at = utcnow()
    session.commit()
    session.refresh(message)
    return message


def get_messages(session: Session, conversation_id: str) -> list[Message]:
    return list(
        session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.sequence)
        )
        .scalars()
        .all()
    )


def delete_message(session: Session, message_id: str) -> bool:
    result = session.execute(delete(Message).where(Message.id == message_id))
    session.commit()
    return result.rowcount > 0


def derive_title(text: str) -> str:
    """First line of the user's opening message, trimmed to something readable."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return DEFAULT_TITLE
    if len(cleaned) <= 60:
        return cleaned
    return cleaned[:57].rstrip() + "…"
