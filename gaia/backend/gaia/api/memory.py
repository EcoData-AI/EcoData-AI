"""Memory management — HTTP shape only, no capture logic here.

Creation is deliberately absent from this router: the only writer is
`gaia.tools.memory.RememberTool`, gated behind the CONFIRM approval dialog in a
chat turn — see `docs/ARCHITECTURE.md`'s "Memory" section. This surface is the
inspectable side the roadmap calls for: search, edit, delete and disable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import MemoryOut, MemoryUpdate
from gaia.services import memory_service
from gaia.services.memory_service import MemoryError

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("", response_model=list[MemoryOut])
def list_memories(
    q: str | None = None,
    kind: str | None = None,
    enabled_only: bool = False,
    session: Session = Depends(get_session),
) -> list[MemoryOut]:
    memories = memory_service.list_memories(session, kind=kind, enabled_only=enabled_only, query=q)
    return [MemoryOut.model_validate(m) for m in memories]


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str, payload: MemoryUpdate, session: Session = Depends(get_session)
) -> MemoryOut:
    try:
        memory = memory_service.update_memory(
            session,
            memory_id,
            content=payload.content,
            importance=payload.importance,
            enabled=payload.enabled,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if memory is None:
        raise HTTPException(status_code=404, detail="No such memory.")
    return MemoryOut.model_validate(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str, session: Session = Depends(get_session)) -> None:
    if not memory_service.delete_memory(session, memory_id):
        raise HTTPException(status_code=404, detail="No such memory.")
