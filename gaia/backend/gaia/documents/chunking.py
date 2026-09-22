"""Chunking — splitting extracted text into passages small enough to cite and
inject into context one at a time.

Character-based, not token-exact, matching `context_builder`'s own budgeting
style (`CHARS_PER_TOKEN` heuristic) rather than pulling in a tokenizer for
this. Chunks overlap so a fact sitting right at a boundary is not split away
from the sentence that explains it.
"""

from __future__ import annotations

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 150

#: How far past `chunk_size` a chunk boundary may be pushed to land on
#: whitespace instead of mid-word. Beyond this, cut at the exact size rather
#: than searching indefinitely (e.g. one very long unbroken token).
MAX_BOUNDARY_SEARCH = 80


def chunk_text(
    text: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            end = _nearest_whitespace(text, end, limit=len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # The overlap region's start is an arbitrary offset, not necessarily
        # at a word boundary — search for the next one too (capped at `end`,
        # so this can never skip past text `end` already covers, which would
        # leave a gap between chunks).
        start = _next_word_start(text, end - overlap, limit=end)

    return chunks


def _nearest_whitespace(text: str, index: int, *, limit: int) -> int:
    """Push `index` forward to the next whitespace, within `MAX_BOUNDARY_SEARCH`
    characters (and never past `limit`) — so a chunk boundary lands between
    words, not mid-word."""
    boundary = min(index + MAX_BOUNDARY_SEARCH, limit)
    for candidate in range(index, boundary):
        if text[candidate].isspace():
            return candidate
    return index


def _next_word_start(text: str, index: int, *, limit: int) -> int:
    """From `index`, find the start of the next word — the first position
    that is either 0 or immediately follows whitespace — within
    `MAX_BOUNDARY_SEARCH` characters and never past `limit`. Falls back to
    `index` unchanged if nothing is found in range."""
    boundary = min(index + MAX_BOUNDARY_SEARCH, limit)
    candidate = index
    while candidate < boundary and not (candidate == 0 or text[candidate - 1].isspace()):
        candidate += 1
    return candidate if candidate < boundary else index
