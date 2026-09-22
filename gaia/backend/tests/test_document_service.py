from __future__ import annotations

import pytest

from gaia.documents.extractors import UnsupportedFormatError
from gaia.services import document_service, project_service


def test_ingest_text_file(session, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Cournot competition assumes firms choose quantities.", encoding="utf-8")

    document = document_service.ingest_file(session, file_path=path, original_filename="notes.txt")

    assert document.title == "notes"
    assert document.media_type == "txt"
    assert document.status == "ready"
    counts = document_service.chunk_counts(session, [document.id])
    assert counts[document.id] == 1


def test_ingest_file_scoped_to_a_project(session, tmp_path):
    project = project_service.create_project(session, name="Cosmos Simulator")
    path = tmp_path / "notes.txt"
    path.write_text("Some notes.", encoding="utf-8")

    document = document_service.ingest_file(
        session, file_path=path, original_filename="notes.txt", project_id=project.id
    )
    assert document.project_id == project.id


def test_ingest_unsupported_format_raises_and_creates_nothing(session, tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")

    with pytest.raises(UnsupportedFormatError):
        document_service.ingest_file(session, file_path=path, original_filename="archive.zip")

    assert document_service.list_documents(session) == []


def test_ingest_file_with_no_extractable_text_raises_and_creates_nothing(session, tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   ", encoding="utf-8")

    with pytest.raises(ValueError, match="no extractable text"):
        document_service.ingest_file(session, file_path=path, original_filename="empty.txt")

    assert document_service.list_documents(session) == []


def test_list_documents_filters_by_project(session, tmp_path):
    project = project_service.create_project(session, name="Cosmos Simulator")
    path = tmp_path / "notes.txt"
    path.write_text("Some notes.", encoding="utf-8")

    document_service.ingest_file(session, file_path=path, original_filename="a.txt")
    document_service.ingest_file(
        session, file_path=path, original_filename="b.txt", project_id=project.id
    )

    assert len(document_service.list_documents(session)) == 2
    assert len(document_service.list_documents(session, project_id=project.id)) == 1


def test_delete_document_removes_the_stored_file_and_cascades_chunks(session, tmp_path, gaia_env):
    from gaia.config import get_settings

    settings = get_settings()
    settings.ensure_directories()
    stored_path = settings.documents_dir / "upload.txt"
    stored_path.write_text("Some notes about oligopoly theory.", encoding="utf-8")

    document = document_service.ingest_file(
        session, file_path=stored_path, original_filename="notes.txt"
    )
    assert stored_path.exists()

    assert document_service.delete_document(session, document.id) is True
    assert not stored_path.exists()
    assert document_service.get_document(session, document.id) is None
    assert document_service.chunk_counts(session, [document.id]) == {}


def test_delete_unknown_document_returns_false(session):
    assert document_service.delete_document(session, "no-such-id") is False
