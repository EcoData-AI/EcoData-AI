from __future__ import annotations

import pytest

from gaia.services import memory_service, project_service
from gaia.services.memory_service import MemoryError


def test_create_and_list_project(session):
    project_service.create_project(session, name="Cosmos Simulator", goals="Model N-body systems")
    projects = project_service.list_projects(session)
    assert len(projects) == 1
    assert projects[0].name == "Cosmos Simulator"
    assert projects[0].archived is False


def test_list_projects_excludes_archived_by_default(session):
    project = project_service.create_project(session, name="Old project")
    project_service.update_project(session, project, archived=True)

    assert project_service.list_projects(session) == []
    assert len(project_service.list_projects(session, include_archived=True)) == 1


def test_update_project(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    updated = project_service.update_project(session, project, description="A physics sandbox")
    assert updated.description == "A physics sandbox"


def test_delete_project(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    assert project_service.delete_project(session, project.id) is True
    assert project_service.list_projects(session) == []
    assert project_service.delete_project(session, project.id) is False


def test_create_and_list_tasks_in_order(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    project_service.create_task(session, project.id, title="design API")
    project_service.create_task(session, project.id, title="scaffold repo")

    tasks = project_service.list_tasks(session, project.id)
    assert [t.title for t in tasks] == ["design API", "scaffold repo"]
    assert [t.order_index for t in tasks] == [0, 1]


def test_list_tasks_open_only_excludes_done(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    todo = project_service.create_task(session, project.id, title="design API")
    project_service.create_task(session, project.id, title="scaffold repo", status="done")

    open_tasks = project_service.list_tasks(session, project.id, open_only=True)
    assert [t.id for t in open_tasks] == [todo.id]


def test_update_and_delete_task(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    task = project_service.create_task(session, project.id, title="design API")

    updated = project_service.update_task(session, task.id, status="done")
    assert updated.status == "done"

    assert project_service.delete_task(session, task.id) is True
    assert project_service.list_tasks(session, project.id) == []


def test_update_unknown_task_returns_none(session):
    assert project_service.update_task(session, "no-such-id", status="done") is None


def test_project_memory_requires_project_id(session):
    with pytest.raises(MemoryError, match="requires a project_id"):
        memory_service.create_memory(session, kind="project", content="uses SI units")


def test_non_project_memory_rejects_project_id(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    with pytest.raises(MemoryError, match="must not have a project_id"):
        memory_service.create_memory(
            session, kind="semantic", content="likes tea", project_id=project.id
        )


def test_project_memories_are_scoped_and_ordered(session):
    project_a = project_service.create_project(session, name="Project A")
    project_b = project_service.create_project(session, name="Project B")

    memory_service.create_memory(
        session, kind="project", content="A: low", project_id=project_a.id, importance=0.1
    )
    high = memory_service.create_memory(
        session, kind="project", content="A: high", project_id=project_a.id, importance=0.9
    )
    memory_service.create_memory(
        session, kind="project", content="B: unrelated", project_id=project_b.id
    )

    scoped = memory_service.project_memories(session, project_a.id)
    assert len(scoped) == 2
    assert scoped[0].id == high.id  # higher importance ranks first
    assert all(m.project_id == project_a.id for m in scoped)


def test_relevant_memories_excludes_project_kind(session):
    project = project_service.create_project(session, name="Cosmos Simulator")
    memory_service.create_memory(session, kind="semantic", content="likes tea")
    memory_service.create_memory(
        session, kind="project", content="uses SI units", project_id=project.id
    )

    relevant = memory_service.relevant_memories(session)
    assert len(relevant) == 1
    assert relevant[0].kind == "semantic"
