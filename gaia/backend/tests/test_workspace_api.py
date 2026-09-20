"""Workspace root CRUD over HTTP."""

from __future__ import annotations


def test_list_roots_starts_empty(client):
    assert client.get("/api/workspace/roots").json() == []


def test_add_list_delete_root(client, tmp_path):
    response = client.post(
        "/api/workspace/roots", json={"path": str(tmp_path), "writable": True}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["writable"] is True
    assert body["enabled"] is True

    listed = client.get("/api/workspace/roots").json()
    assert any(r["id"] == body["id"] for r in listed)

    delete = client.delete(f"/api/workspace/roots/{body['id']}")
    assert delete.status_code == 204
    assert client.get("/api/workspace/roots").json() == []


def test_add_root_rejects_nonexistent_path(client, tmp_path):
    response = client.post(
        "/api/workspace/roots", json={"path": str(tmp_path / "nope"), "writable": False}
    )
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_add_root_rejects_relative_path(client):
    response = client.post(
        "/api/workspace/roots", json={"path": "relative/dir", "writable": False}
    )
    assert response.status_code == 400


def test_delete_unknown_root_returns_404(client):
    response = client.delete("/api/workspace/roots/no-such-id")
    assert response.status_code == 404
