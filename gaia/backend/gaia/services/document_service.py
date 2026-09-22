"""Document ingestion and CRUD.

`ingest_file` builds the extracted, chunked result fully in memory before
writing anything — a file that fails extraction or chunking never leaves a
half-ingested `Document` row behind. Deletion removes the stored copy under
`config.documents_dir` in addition to the database rows (chunks cascade via
the existing FK).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from gaia.config import get_settings
from gaia.core.context_builder import estimate_tokens
from gaia.db.models import Document, DocumentChunk
from gaia.documents.chunking import chunk_text
from gaia.documents.extractors import extract_text, media_type_for

DEFAULT_TITLE = "Untitled document"


def ingest_file(
    session: Session, *, file_path: Path, original_filename: str, project_id: str | None = None
) -> Document:
    media_type = media_type_for(Path(original_filename))
    pages = extract_text(file_path)

    chunk_rows: list[dict] = []
    for text, page in pages:
        for chunk in chunk_text(text):
            chunk_rows.append(
                {
                    "chunk_index": len(chunk_rows),
                    "content": chunk,
                    "token_count": estimate_tokens(chunk),
                    "page": page,
                }
            )

    if not chunk_rows:
        raise ValueError(f"'{original_filename}' has no extractable text.")

    content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
    document = Document(
        title=(Path(original_filename).stem or DEFAULT_TITLE)[:300],
        source_path=original_filename,
        stored_path=str(file_path),
        media_type=media_type,
        byte_size=file_path.stat().st_size,
        content_hash=content_hash,
        project_id=project_id,
        status="ready",
    )
    session.add(document)
    session.flush()  # assigns document.id for the chunk rows below

    for row in chunk_rows:
        session.add(DocumentChunk(document_id=document.id, **row))

    session.commit()
    session.refresh(document)
    return document


def list_documents(session: Session, *, project_id: str | None = None) -> list[Document]:
    stmt = select(Document)
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    stmt = stmt.order_by(Document.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def get_document(session: Session, document_id: str) -> Document | None:
    return session.get(Document, document_id)


def chunk_counts(session: Session, document_ids: list[str]) -> dict[str, int]:
    if not document_ids:
        return {}
    rows = session.execute(
        select(DocumentChunk.document_id, func.count(DocumentChunk.id))
        .where(DocumentChunk.document_id.in_(document_ids))
        .group_by(DocumentChunk.document_id)
    ).all()
    return {document_id: count for document_id, count in rows}


def delete_document(session: Session, document_id: str) -> bool:
    document = session.get(Document, document_id)
    if document is None:
        return False
    stored_path = document.stored_path
    session.delete(document)
    session.commit()
    if stored_path:
        settings = get_settings()
        path = Path(stored_path)
        # Only ever remove a file that is actually inside our own documents
        # directory — belt-and-braces against a corrupted `stored_path` value
        # somehow pointing elsewhere.
        try:
            path.resolve().relative_to(settings.documents_dir.resolve())
        except ValueError:
            return True
        path.unlink(missing_ok=True)
    return True
