"""Document upload/list/delete over HTTP."""

from __future__ import annotations

import io


def test_list_documents_starts_empty(client):
    assert client.get("/api/documents").json() == []


def test_upload_list_and_delete_a_text_document(client):
    response = client.post(
        "/api/documents",
        files={
            "file": (
                "notes.txt",
                io.BytesIO(b"Cournot competition sets quantities."),
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "notes"
    assert body["media_type"] == "txt"
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1

    listed = client.get("/api/documents").json()
    assert len(listed) == 1
    assert listed[0]["chunk_count"] == 1

    fetched = client.get(f"/api/documents/{body['id']}")
    assert fetched.status_code == 200

    deleted = client.delete(f"/api/documents/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/documents").json() == []


def test_upload_with_a_project(client):
    project_id = client.post("/api/projects", json={"name": "Cosmos Simulator"}).json()["id"]
    response = client.post(
        "/api/documents",
        data={"project_id": project_id},
        files={"file": ("notes.txt", io.BytesIO(b"Some notes."), "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["project_id"] == project_id

    assert len(client.get("/api/documents").json()) == 1
    assert len(client.get(f"/api/documents?project_id={project_id}").json()) == 1


def test_upload_rejects_unsupported_extension(client):
    response = client.post(
        "/api/documents",
        files={"file": ("archive.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")},
    )
    assert response.status_code == 400
    assert client.get("/api/documents").json() == []


def test_upload_rejects_oversized_file(client):
    from gaia.api.documents import MAX_UPLOAD_BYTES

    oversized = b"a" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/api/documents",
        files={"file": ("big.txt", io.BytesIO(oversized), "text/plain")},
    )
    assert response.status_code == 400
    assert client.get("/api/documents").json() == []


def test_upload_rejects_file_with_no_extractable_text(client):
    response = client.post(
        "/api/documents",
        files={"file": ("empty.txt", io.BytesIO(b"   "), "text/plain")},
    )
    assert response.status_code == 400
    assert client.get("/api/documents").json() == []


def test_get_unknown_document_returns_404(client):
    assert client.get("/api/documents/no-such-id").status_code == 404


def test_delete_unknown_document_returns_404(client):
    assert client.delete("/api/documents/no-such-id").status_code == 404


def test_upload_leaves_nothing_on_disk_when_rejected(client, gaia_env):
    from gaia.config import get_settings

    settings = get_settings()
    before = set(settings.documents_dir.iterdir()) if settings.documents_dir.exists() else set()

    client.post(
        "/api/documents",
        files={"file": ("archive.zip", io.BytesIO(b"PK\x03\x04"), "application/zip")},
    )

    after = set(settings.documents_dir.iterdir()) if settings.documents_dir.exists() else set()
    assert before == after
