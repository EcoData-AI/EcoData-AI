"""Workspace root management — HTTP shape only, no filesystem logic here.

Registering a root is a user-initiated configuration change (like setting a
provider API key), not a model-invoked tool call — it carries no `ToolCall`
audit row and no risk-level gate. `gaia/tools/filesystem.py` is what actually
enforces containment against these rows once a tool call happens.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import WorkspaceRootCreate, WorkspaceRootOut
from gaia.services import workspace_service
from gaia.services.workspace_service import WorkspaceRootError

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


@router.get("/roots", response_model=list[WorkspaceRootOut])
def list_roots(session: Session = Depends(get_session)) -> list[WorkspaceRootOut]:
    return [WorkspaceRootOut.model_validate(r) for r in workspace_service.list_roots(session)]


@router.post("/roots", response_model=WorkspaceRootOut, status_code=status.HTTP_201_CREATED)
def add_root(
    payload: WorkspaceRootCreate, session: Session = Depends(get_session)
) -> WorkspaceRootOut:
    try:
        root = workspace_service.add_root(session, path=payload.path, writable=payload.writable)
    except WorkspaceRootError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkspaceRootOut.model_validate(root)


@router.delete("/roots/{root_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_root(root_id: str, session: Session = Depends(get_session)) -> None:
    if not workspace_service.remove_root(session, root_id):
        raise HTTPException(status_code=404, detail="No such workspace root.")
