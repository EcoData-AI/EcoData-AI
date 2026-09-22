"""Project and task persistence. CRUD shape mirrors `conversation_service.py`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.models import Project, ProjectTask

DEFAULT_TASK_STATUS = "todo"


def create_project(
    session: Session,
    *,
    name: str,
    description: str | None = None,
    goals: str | None = None,
    workspace_path: str | None = None,
) -> Project:
    project = Project(
        name=name.strip(), description=description, goals=goals, workspace_path=workspace_path
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def get_project(session: Session, project_id: str) -> Project | None:
    return session.get(Project, project_id)


def list_projects(session: Session, *, include_archived: bool = False) -> list[Project]:
    stmt = select(Project)
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    stmt = stmt.order_by(Project.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def update_project(session: Session, project: Project, **fields) -> Project:
    for key, value in fields.items():
        if value is not None and hasattr(project, key):
            setattr(project, key, value)
    session.commit()
    session.refresh(project)
    return project


def delete_project(session: Session, project_id: str) -> bool:
    project = session.get(Project, project_id)
    if project is None:
        return False
    session.delete(project)
    session.commit()
    return True


def create_task(
    session: Session,
    project_id: str,
    *,
    title: str,
    notes: str | None = None,
    status: str = DEFAULT_TASK_STATUS,
) -> ProjectTask:
    existing = (
        session.execute(select(ProjectTask).where(ProjectTask.project_id == project_id))
        .scalars()
        .all()
    )
    task = ProjectTask(
        project_id=project_id,
        title=title.strip(),
        notes=notes,
        status=status,
        order_index=len(existing),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def list_tasks(session: Session, project_id: str, *, open_only: bool = False) -> list[ProjectTask]:
    stmt = select(ProjectTask).where(ProjectTask.project_id == project_id)
    if open_only:
        stmt = stmt.where(ProjectTask.status != "done")
    stmt = stmt.order_by(ProjectTask.order_index)
    return list(session.execute(stmt).scalars().all())


def update_task(session: Session, task_id: str, **fields) -> ProjectTask | None:
    task = session.get(ProjectTask, task_id)
    if task is None:
        return None
    for key, value in fields.items():
        if value is not None and hasattr(task, key):
            setattr(task, key, value)
    session.commit()
    session.refresh(task)
    return task


def delete_task(session: Session, task_id: str) -> bool:
    task = session.get(ProjectTask, task_id)
    if task is None:
        return False
    session.delete(task)
    session.commit()
    return True
