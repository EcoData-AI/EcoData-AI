from __future__ import annotations

from gaia.db.models import Document, DocumentChunk
from gaia.documents import retrieval
from gaia.services import project_service


def _make_document(session, *, title="Doc", project_id=None, status="ready") -> Document:
    document = Document(title=title, media_type="txt", project_id=project_id, status=status)
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _add_chunk(session, document, content, *, chunk_index=0, page=None) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=document.id, chunk_index=chunk_index, content=content, page=page
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    return chunk


def test_search_ranks_exact_term_match_above_unrelated_chunk(session):
    document = _make_document(session)
    relevant = _add_chunk(session, document, "Cournot competition sets quantities, not prices.")
    _add_chunk(session, document, "The weather today is sunny with a light breeze.", chunk_index=1)

    results = retrieval.search(session, "Cournot competition")
    assert results
    assert results[0].id == relevant.id


def test_search_with_no_matches_returns_nothing(session):
    document = _make_document(session)
    _add_chunk(session, document, "Cournot competition sets quantities, not prices.")

    assert retrieval.search(session, "quantum entanglement teleportation") == []


def test_search_respects_limit(session):
    document = _make_document(session)
    for i in range(10):
        _add_chunk(session, document, f"passage {i} discusses oligopoly theory", chunk_index=i)

    results = retrieval.search(session, "oligopoly theory", limit=3)
    assert len(results) == 3


def test_search_excludes_non_ready_documents(session):
    pending = _make_document(session, status="pending")
    _add_chunk(session, pending, "Cournot competition sets quantities.")

    assert retrieval.search(session, "Cournot competition") == []


def test_search_scopes_to_project(session):
    project_a = project_service.create_project(session, name="Project A")
    project_b = project_service.create_project(session, name="Project B")
    doc_a = _make_document(session, title="A", project_id=project_a.id)
    doc_b = _make_document(session, title="B", project_id=project_b.id)
    chunk_a = _add_chunk(session, doc_a, "Cournot competition in project A.")
    _add_chunk(session, doc_b, "Cournot competition in project B.")

    results = retrieval.search(session, "Cournot competition", project_id=project_a.id)
    assert [r.id for r in results] == [chunk_a.id]


def test_search_with_empty_query_returns_nothing(session):
    document = _make_document(session)
    _add_chunk(session, document, "Cournot competition sets quantities.")

    assert retrieval.search(session, "   ") == []


def test_search_with_no_documents_returns_nothing(session):
    assert retrieval.search(session, "anything at all") == []
