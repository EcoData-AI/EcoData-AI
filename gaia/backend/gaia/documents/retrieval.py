"""BM25 (Okapi) retrieval over `DocumentChunk` rows — lexical, not semantic.

No embedding model exists in this codebase (see `docs/ARCHITECTURE.md`,
"Documents and retrieval", for why: no chat provider here has a uniformly
available embeddings API, and coupling document search to whichever one is
configured would be a strange dependency). BM25 is computed fresh on every
call rather than against a persisted index — fine at the scale one person's
own documents reach, and it means `DocumentChunk.embedding` can stay unused
without anything here depending on it.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.models import Document, DocumentChunk

#: Standard Okapi BM25 parameters.
K1 = 1.5
B = 0.75

DEFAULT_LIMIT = 5

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def search(
    session: Session, query: str, *, project_id: str | None = None, limit: int = DEFAULT_LIMIT
) -> list[DocumentChunk]:
    """Rank `DocumentChunk` rows against `query`, best first.

    Only `Document.status == "ready"` chunks are candidates. `project_id`
    scopes to one project's documents when given, or every document
    otherwise. Never returns a chunk with a zero BM25 score — a query that
    matches nothing gets nothing back, rather than a low-relevance chunk
    dressed up as a citation.
    """
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    stmt = select(DocumentChunk).join(Document).where(Document.status == "ready")
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    chunks = list(session.execute(stmt).scalars().all())
    if not chunks:
        return []

    tokenized = [_tokenize(chunk.content) for chunk in chunks]
    doc_freq: Counter[str] = Counter()
    for tokens in tokenized:
        doc_freq.update(set(tokens))

    n_docs = len(chunks)
    avg_len = sum(len(t) for t in tokenized) / n_docs

    idf = {
        term: math.log((n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1.0)
        for term in set(query_terms)
        if doc_freq[term] > 0
    }
    if not idf:
        return []

    scored: list[tuple[float, DocumentChunk]] = []
    for chunk, tokens in zip(chunks, tokenized, strict=True):
        if not tokens:
            continue
        counts = Counter(tokens)
        doc_len = len(tokens)
        score = 0.0
        for term in query_terms:
            term_idf = idf.get(term)
            if term_idf is None:
                continue
            freq = counts.get(term, 0)
            if freq == 0:
                continue
            numerator = freq * (K1 + 1)
            denominator = freq + K1 * (1 - B + B * doc_len / avg_len)
            score += term_idf * (numerator / denominator)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [chunk for _, chunk in scored[:limit]]
