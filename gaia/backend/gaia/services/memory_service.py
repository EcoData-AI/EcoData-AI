"""Persistent memory — facts GAIA was explicitly asked to remember.

The only *automatic* writer is `gaia.tools.memory.RememberTool`, itself gated
CONFIRM so the user sees exactly what will be stored before it happens — see
`docs/ARCHITECTURE.md`'s "Memory" section. `kind="project"` is the one
exception: it is created manually from the Project page
(`api/projects.py`'s `POST /api/projects/{id}/memories`), never by the model,
because it is scoped to a project rather than to "the user" in general.

`kind` is restricted to `"semantic" | "episodic" | "project"`. `"knowledge"`
belongs to Milestone 5 (documents/RAG), not here.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.base import utcnow
from gaia.db.models import Memory

ALLOWED_KINDS = ("semantic", "episodic", "project")

#: What `RememberTool` (the model-facing path) may create. Deliberately excludes
#: `"project"` — a project memory is scoped to one project and is only ever
#: created manually from that project's page (`api/projects.py`), never by the
#: model, which has no notion of "the current project" to scope one to.
MODEL_ALLOWED_KINDS = ("semantic", "episodic")

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
    project_id: str | None = None,
    importance: float = 0.5,
) -> Memory:
    if kind not in ALLOWED_KINDS:
        raise MemoryError(f"'kind' must be one of {ALLOWED_KINDS}, not '{kind}'.")
    if not content or not content.strip():
        raise MemoryError("content must not be empty.")
    if kind == "project" and not project_id:
        raise MemoryError("a 'project' memory requires a project_id.")
    if kind != "project" and project_id:
        raise MemoryError(f"'{kind}' memories must not have a project_id.")

    memory = Memory(
        kind=kind,
        content=content.strip(),
        source=source,
        project_id=project_id,
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
    project_id: str | None = None,
    enabled_only: bool = False,
    query: str | None = None,
) -> list[Memory]:
    stmt = select(Memory)
    if kind is not None:
        stmt = stmt.where(Memory.kind == kind)
    if project_id is not None:
        stmt = stmt.where(Memory.project_id == project_id)
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
    """Memories to inject into every turn's context, regardless of project.

    No embeddings yet (that's Milestone 5's job) — every enabled non-project
    memory is a candidate, ranked by how important it was marked and how
    recently it was added, capped at `limit` so a long list of memories can
    never crowd out the conversation itself. `kind="project"` is excluded
    here on purpose — those are scoped to one project and only reach context
    through `project_memories()`, when a conversation is actually assigned to
    that project.
    """
    stmt = (
        select(Memory)
        .where(Memory.enabled.is_(True), Memory.kind != "project")
        .order_by(Memory.importance.desc(), Memory.created_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def project_memories(
    session: Session, project_id: str, *, limit: int = DEFAULT_RELEVANCE_LIMIT
) -> list[Memory]:
    """Memories scoped to one project, for a conversation assigned to it.

    Same ranking as `relevant_memories`, just filtered to `kind="project"` and
    this specific `project_id`.
    """
    stmt = (
        select(Memory)
        .where(
            Memory.enabled.is_(True),
            Memory.kind == "project",
            Memory.project_id == project_id,
        )
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
