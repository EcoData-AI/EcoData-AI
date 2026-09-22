"""Projects — HTTP shape only, mirrors `api/workspace.py`/`api/memory.py`.

`POST /api/projects/{id}/memories` is the one place memory creation happens
outside the `remember` tool — see `services/memory_service.py`'s module
docstring and `MODEL_ALLOWED_KINDS` for why that split exists. Editing or
deleting a project memory reuses the general `/api/memory/{id}` routes; no
project-scoped PATCH/DELETE is duplicated here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from gaia.db.session import get_session
from gaia.schemas.api import (
    MemoryOut,
    ProjectCreate,
    ProjectMemoryCreate,
    ProjectOut,
    ProjectTaskCreate,
    ProjectTaskOut,
    ProjectTaskUpdate,
    ProjectUpdate,
)
from gaia.services import memory_service, project_service
from gaia.services.memory_service import MemoryError

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_project_or_404(session: Session, project_id: str):
    project = project_service.get_project(session, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(
    include_archived: bool = False, session: Session = Depends(get_session)
) -> list[ProjectOut]:
    projects = project_service.list_projects(session, include_archived=include_archived)
    return [ProjectOut.model_validate(p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> ProjectOut:
    project = project_service.create_project(
        session,
        name=payload.name,
        description=payload.description,
        goals=payload.goals,
        workspace_path=payload.workspace_path,
    )
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    return ProjectOut.model_validate(_get_project_or_404(session, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, payload: ProjectUpdate, session: Session = Depends(get_session)
) -> ProjectOut:
    project = _get_project_or_404(session, project_id)
    project_service.update_project(session, project, **payload.model_dump(exclude_unset=True))
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, session: Session = Depends(get_session)) -> None:
    if not project_service.delete_project(session, project_id):
        raise HTTPException(status_code=404, detail="No such project.")


@router.get("/{project_id}/tasks", response_model=list[ProjectTaskOut])
def list_tasks(
    project_id: str, session: Session = Depends(get_session)
) -> list[ProjectTaskOut]:
    _get_project_or_404(session, project_id)
    tasks = project_service.list_tasks(session, project_id)
    return [ProjectTaskOut.model_validate(t) for t in tasks]


@router.post(
    "/{project_id}/tasks", response_model=ProjectTaskOut, status_code=status.HTTP_201_CREATED
)
def create_task(
    project_id: str, payload: ProjectTaskCreate, session: Session = Depends(get_session)
) -> ProjectTaskOut:
    _get_project_or_404(session, project_id)
    task = project_service.create_task(
        session, project_id, title=payload.title, notes=payload.notes, status=payload.status
    )
    return ProjectTaskOut.model_validate(task)


@router.patch("/{project_id}/tasks/{task_id}", response_model=ProjectTaskOut)
def update_task(
    project_id: str,
    task_id: str,
    payload: ProjectTaskUpdate,
    session: Session = Depends(get_session),
) -> ProjectTaskOut:
    _get_project_or_404(session, project_id)
    task = project_service.update_task(session, task_id, **payload.model_dump(exclude_unset=True))
    if task is None:
        raise HTTPException(status_code=404, detail="No such task.")
    return ProjectTaskOut.model_validate(task)


@router.delete("/{project_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(project_id: str, task_id: str, session: Session = Depends(get_session)) -> None:
    _get_project_or_404(session, project_id)
    if not project_service.delete_task(session, task_id):
        raise HTTPException(status_code=404, detail="No such task.")


@router.get("/{project_id}/memories", response_model=list[MemoryOut])
def list_project_memories(
    project_id: str, session: Session = Depends(get_session)
) -> list[MemoryOut]:
    _get_project_or_404(session, project_id)
    memories = memory_service.list_memories(session, kind="project", project_id=project_id)
    return [MemoryOut.model_validate(m) for m in memories]


@router.post(
    "/{project_id}/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED
)
def create_project_memory(
    project_id: str, payload: ProjectMemoryCreate, session: Session = Depends(get_session)
) -> MemoryOut:
    _get_project_or_404(session, project_id)
    try:
        memory = memory_service.create_memory(
            session,
            kind="project",
            content=payload.content,
            project_id=project_id,
            importance=payload.importance,
        )
    except MemoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemoryOut.model_validate(memory)
