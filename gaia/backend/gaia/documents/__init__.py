"""Document ingestion and retrieval (Milestone 5).

Mirrors `gaia/tools/`'s per-concern layout: `extractors.py` (text out of a
file), `chunking.py` (text into passages), `retrieval.py` (BM25 search over
chunks). `services/document_service.py` orchestrates all three; `api/
documents.py` is the HTTP surface.
"""

from __future__ import annotations
