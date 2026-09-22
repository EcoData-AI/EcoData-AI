"""Documents — HTTP shape only, mirrors `api/workspace.py`.

Extraction/chunking failures and unsupported formats are rejected here as
400s before anything is written to `config.documents_dir` — see
`services/document_service.ingest_file`'s own docstring for why no partial
`Document` row is ever possible.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from gaia.config import get_settings
from gaia.db.session import get_session
from gaia.documents.extractors import UnsupportedFormatError, media_type_for
from gaia.schemas.api import DocumentOut
from gaia.services import document_service

router = APIRouter(prefix="/api/documents", tags=["documents"])

#: Matches the order of magnitude `filesystem.py`'s MAX_WRITE_BYTES uses for a
#: single write, scaled up for a real document rather than a tool-generated file.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _out(document, chunk_count: int) -> DocumentOut:
    result = DocumentOut.model_validate(document)
    result.chunk_count = chunk_count
    return result


@router.get("", response_model=list[DocumentOut])
def list_documents(
    project_id: str | None = None, session: Session = Depends(get_session)
) -> list[DocumentOut]:
    documents = document_service.list_documents(session, project_id=project_id)
    counts = document_service.chunk_counts(session, [d.id for d in documents])
    return [_out(d, counts.get(d.id, 0)) for d in documents]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    project_id: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> DocumentOut:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename was provided.")

    try:
        media_type_for(Path(file.filename))
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"'{file.filename}' is over the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
        )

    settings = get_settings()
    settings.ensure_directories()
    stored_path = settings.documents_dir / f"{uuid.uuid4().hex}{Path(file.filename).suffix}"
    stored_path.write_bytes(payload)

    try:
        document = document_service.ingest_file(
            session,
            file_path=stored_path,
            original_filename=file.filename,
            project_id=project_id,
        )
    except (UnsupportedFormatError, ValueError, OSError) as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    counts = document_service.chunk_counts(session, [document.id])
    return _out(document, counts.get(document.id, 0))


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, session: Session = Depends(get_session)) -> DocumentOut:
    document = document_service.get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="No such document.")
    counts = document_service.chunk_counts(session, [document.id])
    return _out(document, counts.get(document.id, 0))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, session: Session = Depends(get_session)) -> None:
    if not document_service.delete_document(session, document_id):
        raise HTTPException(status_code=404, detail="No such document.")
