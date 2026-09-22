"""Persistent memory — facts GAIA was explicitly asked to remember.

Nothing here is written automatically. The only writer is `gaia.tools.memory.
RememberTool`, itself gated CONFIRM so the user sees exactly what will be
stored before it happens — see `docs/ARCHITECTURE.md`'s "Memory" section.
CRUD shape mirrors `workspace_service.py`.

`kind` is restricted to `"semantic" | "episodic"` for this slice. `"project"`
arrives once conversations can be assigned to a project; `"knowledge"` belongs
to Milestone 5 (documents/RAG), not here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.base import utcnow
from gaia.db.models import Memory

ALLOWED_KINDS = ("semantic", "episodic")

#: Cap on how many memories are ever injected into one turn's context — an
#: unbounded list would eventually crowd out the conversation itself.
DEFAULT_RELEVANCE_LIMIT = 20


class MemoryError(ValueError):
    """A memory could not be created or updated as requested."""


def create_memory(
    session: Session,
    *,
    kind: str,
    content: str,
    source: str | None = None,
    importance: float = 0.5,
) -> Memory:
    if kind not in ALLOWED_KINDS:
        raise MemoryError(f"'kind' must be one of {ALLOWED_KINDS}, not '{kind}'.")
    if not content or not content.strip():
        raise MemoryError("content must not be empty.")

    memory = Memory(
        kind=kind,
        content=content.strip(),
        source=source,
        importance=importance,
        enabled=True,
    )
    session.add(memory)
    session.commit()
    session.refresh(memory)
    return memory


def list_memories(
    session: Session,
    *,
    kind: str | None = None,
    enabled_only: bool = False,
    query: str | None = None,
) -> list[Memory]:
    stmt = select(Memory)
    if kind is not None:
        stmt = stmt.where(Memory.kind == kind)
    if enabled_only:
        stmt = stmt.where(Memory.enabled.is_(True))
    if query and query.strip():
        stmt = stmt.where(Memory.content.ilike(f"%{query.strip()}%"))
    stmt = stmt.order_by(Memory.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def update_memory(
    session: Session,
    memory_id: str,
    *,
    content: str | None = None,
    importance: float | None = None,
    enabled: bool | None = None,
) -> Memory | None:
    memory = session.get(Memory, memory_id)
    if memory is None:
        return None
    if content is not None:
        if not content.strip():
            raise MemoryError("content must not be empty.")
        memory.content = content.strip()
    if importance is not None:
        memory.importance = importance
    if enabled is not None:
        memory.enabled = enabled
    session.commit()
    session.refresh(memory)
    return memory


def delete_memory(session: Session, memory_id: str) -> bool:
    memory = session.get(Memory, memory_id)
    if memory is None:
        return False
    session.delete(memory)
    session.commit()
    return True


def relevant_memories(session: Session, *, limit: int = DEFAULT_RELEVANCE_LIMIT) -> list[Memory]:
    """Memories to inject into the next turn's context.

    No embeddings yet (that's Milestone 5's job) — every enabled memory is a
    candidate, ranked by how important it was marked and how recently it was
    added, capped at `limit` so a long list of memories can never crowd out
    the conversation itself.
    """
    stmt = (
        select(Memory)
        .where(Memory.enabled.is_(True))
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def mark_used(session: Session, memory_ids: list[str]) -> None:
    if not memory_ids:
        return
    session.execute(
        Memory.__table__.update()
        .where(Memory.id.in_(memory_ids))
        .values(last_used_at=utcnow())
    )
    session.commit()
