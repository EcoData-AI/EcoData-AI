from __future__ import annotations

import pytest

from gaia.documents.chunking import chunk_text


def test_short_text_produces_one_chunk():
    assert chunk_text("A short passage.") == ["A short passage."]


def test_empty_text_produces_no_chunks():
    assert chunk_text("   ") == []
    assert chunk_text("") == []


def test_long_text_is_split_into_multiple_chunks():
    text = " ".join(f"word{i}" for i in range(500))  # well over the default chunk_size
    chunks = chunk_text(text)
    assert len(chunks) > 1
    # Every chunk should respect the size limit plus the whitespace-boundary slack.
    for chunk in chunks:
        assert len(chunk) <= 1000 + 80


def test_chunks_overlap():
    text = " ".join(f"word{i}" for i in range(500))
    chunks = chunk_text(text, chunk_size=200, overlap=50)
    assert len(chunks) > 1
    # The end of one chunk and the start of the next should share some text.
    first_tail = chunks[0][-30:]
    assert any(word in chunks[1] for word in first_tail.split() if len(word) > 3)


def test_reassembled_chunks_cover_the_whole_text():
    text = "alpha " * 300
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    covered = set()
    for chunk in chunks:
        covered.update(chunk.split())
    assert covered == {"alpha"}


def test_chunk_boundaries_prefer_whitespace_over_mid_word():
    text = "abcdefgh " * 50  # no long unbroken run, so every boundary can land on whitespace
    chunks = chunk_text(text, chunk_size=50, overlap=10)
    for chunk in chunks:
        assert not chunk.startswith("bcdefgh")  # would indicate a mid-word cut


def test_rejects_invalid_chunk_size_and_overlap():
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=0)
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=100, overlap=100)
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=100, overlap=-1)
