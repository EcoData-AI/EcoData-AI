"""Memory CRUD over HTTP — search/edit/delete/disable, no creation endpoint.

Creation only ever happens through `RememberTool`; see test_tools_memory.py and
test_chat_tools_confirm.py for that path.
"""

from __future__ import annotations


def test_list_memories_starts_empty(client):
    assert client.get("/api/memory").json() == []


def test_list_memories_filters_by_query_and_kind(client, session):
    from gaia.services import memory_service

    memory_service.create_memory(session, kind="semantic", content="likes tea")
    memory_service.create_memory(session, kind="episodic", content="asked about game theory")

    assert len(client.get("/api/memory").json()) == 2
    assert len(client.get("/api/memory?kind=semantic").json()) == 1
    assert len(client.get("/api/memory?q=game").json()) == 1


def test_update_memory_content_importance_and_enabled(client, session):
    from gaia.services import memory_service

    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")

    response = client.patch(f"/api/memory/{memory.id}", json={"content": "likes coffee"})
    assert response.status_code == 200
    assert response.json()["content"] == "likes coffee"

    response = client.patch(f"/api/memory/{memory.id}", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = client.patch(f"/api/memory/{memory.id}", json={"importance": 0.9})
    assert response.status_code == 200
    assert response.json()["importance"] == 0.9


def test_update_memory_rejects_empty_content(client, session):
    from gaia.services import memory_service

    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")
    response = client.patch(f"/api/memory/{memory.id}", json={"content": ""})
    assert response.status_code == 422  # min_length=1 on MemoryUpdate.content


def test_update_unknown_memory_returns_404(client):
    response = client.patch("/api/memory/no-such-id", json={"content": "x"})
    assert response.status_code == 404


def test_delete_memory(client, session):
    from gaia.services import memory_service

    memory = memory_service.create_memory(session, kind="semantic", content="likes tea")
    response = client.delete(f"/api/memory/{memory.id}")
    assert response.status_code == 204
    assert client.get("/api/memory").json() == []


def test_delete_unknown_memory_returns_404(client):
    response = client.delete("/api/memory/no-such-id")
    assert response.status_code == 404
