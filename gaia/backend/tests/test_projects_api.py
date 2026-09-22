"""Projects, tasks and project-scoped memory over HTTP."""

from __future__ import annotations


def test_list_projects_starts_empty(client):
    assert client.get("/api/projects").json() == []


def test_create_get_update_delete_project(client):
    created = client.post("/api/projects", json={"name": "Cosmos Simulator", "goals": "N-body"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Cosmos Simulator"
    assert body["archived"] is False

    fetched = client.get(f"/api/projects/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["goals"] == "N-body"

    updated = client.patch(f"/api/projects/{body['id']}", json={"description": "A sandbox"})
    assert updated.status_code == 200
    assert updated.json()["description"] == "A sandbox"

    deleted = client.delete(f"/api/projects/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/projects").json() == []


def test_get_unknown_project_returns_404(client):
    assert client.get("/api/projects/no-such-id").status_code == 404


def test_create_project_rejects_empty_name(client):
    response = client.post("/api/projects", json={"name": ""})
    assert response.status_code == 422


def test_archived_project_excluded_by_default(client):
    body = client.post("/api/projects", json={"name": "Old"}).json()
    client.patch(f"/api/projects/{body['id']}", json={"archived": True})

    assert client.get("/api/projects").json() == []
    assert len(client.get("/api/projects?include_archived=true").json()) == 1


def test_task_crud(client):
    project_id = client.post("/api/projects", json={"name": "Cosmos Simulator"}).json()["id"]

    created = client.post(f"/api/projects/{project_id}/tasks", json={"title": "design API"})
    assert created.status_code == 201
    task = created.json()
    assert task["status"] == "todo"
    assert task["order_index"] == 0

    listed = client.get(f"/api/projects/{project_id}/tasks").json()
    assert len(listed) == 1

    updated = client.patch(
        f"/api/projects/{project_id}/tasks/{task['id']}", json={"status": "done"}
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"

    deleted = client.delete(f"/api/projects/{project_id}/tasks/{task['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/{project_id}/tasks").json() == []


def test_task_routes_404_for_unknown_project(client):
    assert client.get("/api/projects/no-such-id/tasks").status_code == 404
    assert client.post("/api/projects/no-such-id/tasks", json={"title": "x"}).status_code == 404


def test_update_unknown_task_returns_404(client):
    project_id = client.post("/api/projects", json={"name": "Cosmos Simulator"}).json()["id"]
    response = client.patch(
        f"/api/projects/{project_id}/tasks/no-such-id", json={"status": "done"}
    )
    assert response.status_code == 404


def test_project_memory_create_list_and_edit_via_general_route(client):
    project_id = client.post("/api/projects", json={"name": "Cosmos Simulator"}).json()["id"]

    created = client.post(f"/api/projects/{project_id}/memories", json={"content": "uses SI units"})
    assert created.status_code == 201
    memory = created.json()
    assert memory["kind"] == "project"
    assert memory["project_id"] == project_id

    listed = client.get(f"/api/projects/{project_id}/memories").json()
    assert len(listed) == 1

    # Editing/deleting a project memory reuses the general /api/memory routes.
    edited = client.patch(f"/api/memory/{memory['id']}", json={"content": "uses metric units"})
    assert edited.status_code == 200
    assert edited.json()["content"] == "uses metric units"

    # It also shows up in the general Memory screen's listing.
    general = client.get("/api/memory").json()
    assert any(m["id"] == memory["id"] for m in general)

    deleted = client.delete(f"/api/memory/{memory['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/{project_id}/memories").json() == []


def test_project_memory_routes_404_for_unknown_project(client):
    assert client.get("/api/projects/no-such-id/memories").status_code == 404
    response = client.post("/api/projects/no-such-id/memories", json={"content": "x"})
    assert response.status_code == 404


def test_deleting_a_project_cascades_tasks_and_memories_and_unassigns_conversations(
    client, session
):
    from sqlalchemy import select

    from gaia.db.models import Memory, ProjectTask

    project_id = client.post("/api/projects", json={"name": "Cosmos Simulator"}).json()["id"]
    task_id = client.post(
        f"/api/projects/{project_id}/tasks", json={"title": "design API"}
    ).json()["id"]
    memory_id = client.post(
        f"/api/projects/{project_id}/memories", json={"content": "uses SI units"}
    ).json()["id"]
    conversation_id = client.post(
        "/api/conversations", json={"project_id": project_id}
    ).json()["id"]

    response = client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 204

    assert session.get(ProjectTask, task_id) is None
    remaining = session.execute(select(Memory).where(Memory.id == memory_id)).scalar_one_or_none()
    assert remaining is None

    conversation = client.get(f"/api/conversations/{conversation_id}").json()
    assert conversation["project_id"] is None
