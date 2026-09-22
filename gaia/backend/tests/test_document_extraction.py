"""Text extraction per format.

The PDF fixture is built directly with pypdf's own object model (a blank page
plus a minimal content stream and Helvetica font resource) rather than adding
a second PDF-authoring dependency just for tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from gaia.documents.extractors import UnsupportedFormatError, extract_text, media_type_for


def _write_pdf(path: Path, pages: list[str]) -> None:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=200, height=200)

        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)  # noqa: SLF001 - no public API for this

        resources = DictionaryObject()
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font_ref
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources

        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)  # noqa: SLF001

    with path.open("wb") as handle:
        writer.write(handle)


def test_media_type_for_supported_and_unsupported_extensions():
    assert media_type_for(Path("notes.txt")) == "txt"
    assert media_type_for(Path("readme.md")) == "md"
    assert media_type_for(Path("data.csv")) == "csv"
    assert media_type_for(Path("report.pdf")) == "pdf"
    assert media_type_for(Path("script.py")) == "py"
    with pytest.raises(UnsupportedFormatError):
        media_type_for(Path("archive.zip"))


def test_extract_plain_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Cournot competition assumes firms choose quantities.", encoding="utf-8")
    pages = extract_text(path)
    assert pages == [("Cournot competition assumes firms choose quantities.", None)]


def test_extract_markdown_and_csv_as_plain_text(tmp_path):
    md = tmp_path / "readme.md"
    md.write_text("# Title\n\nSome content.", encoding="utf-8")
    assert extract_text(md)[0][0] == "# Title\n\nSome content."

    csv = tmp_path / "data.csv"
    csv.write_text("name,value\nfoo,1\n", encoding="utf-8")
    assert extract_text(csv)[0][0] == "name,value\nfoo,1\n"


def test_extract_empty_text_file_returns_no_pages(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n  ", encoding="utf-8")
    assert extract_text(path) == []


def test_extract_non_utf8_text_file_raises(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        extract_text(path)


def test_extract_unsupported_extension_raises(tmp_path):
    path = tmp_path / "archive.zip"
    path.write_bytes(b"PK\x03\x04")
    with pytest.raises(UnsupportedFormatError):
        extract_text(path)


def test_extract_pdf_returns_one_pair_per_page(tmp_path):
    path = tmp_path / "report.pdf"
    _write_pdf(path, ["First page text", "Second page text"])

    pages = extract_text(path)
    assert [page for _, page in pages] == [1, 2]
    assert "First page text" in pages[0][0]
    assert "Second page text" in pages[1][0]


def test_extract_corrupt_pdf_raises(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not actually a pdf")
    with pytest.raises(ValueError):
        extract_text(path)
