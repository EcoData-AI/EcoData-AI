"""Text extraction per file format.

`extract_text` is the only entry point: it dispatches on file extension and
always returns a list of `(text, page)` pairs — one pair per page for PDFs (so
`DocumentChunk.page` stays meaningful for citations), a single pair with
`page=None` for everything else. CSV is read as raw text, not parsed into
rows — this slice chunks it the same way as any other text file rather than
giving it special tabular handling.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

#: Extensions read as plain UTF-8 text. `.csv` is deliberately in this list,
#: not handled separately — see the module docstring.
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".sh",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".sql",
}

SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf"}


class UnsupportedFormatError(ValueError):
    """The file's extension is not one `extract_text` knows how to read."""


def media_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"'{suffix or path.name}' is not a supported document format. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    return "pdf" if suffix == ".pdf" else suffix.lstrip(".")


def extract_text(path: Path) -> list[tuple[str, int | None]]:
    """Extract text from `path`. Raises `UnsupportedFormatError` for an
    unrecognised extension, `OSError` for a file that cannot be read, and
    `ValueError` for a file that claims a supported extension but is not
    actually readable as that format (e.g. a corrupt PDF)."""
    media_type = media_type_for(path)

    if media_type == "pdf":
        return _extract_pdf(path)
    return _extract_plain_text(path)


def _extract_pdf(path: Path) -> list[tuple[str, int | None]]:
    try:
        reader = PdfReader(path)
        pages = [(page.extract_text() or "", index + 1) for index, page in enumerate(reader.pages)]
    except PdfReadError as exc:
        raise ValueError(f"could not read '{path.name}' as a PDF: {exc}") from exc
    # A page with no extractable text (e.g. a scanned image) contributes
    # nothing rather than an empty chunk — OCR is out of scope for this slice.
    return [(text, page) for text, page in pages if text.strip()]


def _extract_plain_text(path: Path) -> list[tuple[str, int | None]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"'{path.name}' is not valid UTF-8 text") from exc
    return [(text, None)] if text.strip() else []
