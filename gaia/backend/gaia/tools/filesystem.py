"""Filesystem tools — workspace-scoped read and write.

Two separate tool classes, not one tool with a risk-varying `operation`
argument: `Tool.risk_level` is a fixed class attribute the registry enforces
before anything runs (see `calculator.py`/`python_sandbox.py`), and per that
design it must never depend on what the model requests. Reading and writing
are genuinely different risk classes, so they are genuinely different tools.

Containment (`services/workspace_service.resolve_within_workspace`, shared with
`terminal.py`) canonicalises the requested path (`Path.resolve`, which
collapses `..` and follows symlinks) and re-checks it falls inside an enabled
`WorkspaceRoot` row — never string or prefix matching on the raw path, which
those can defeat. No `WorkspaceRoot` rows exist until one is added
(`POST /api/workspace/roots`); with none configured, both tools say so
plainly rather than falling back to some default directory.

Deletion is not implemented. Per docs/SECURITY.md's risk table, recursive
deletion is BLOCKED-tier; rather than define a tool and mark it BLOCKED
(which would still need real design later — selective deletion, confirmation
wording, trash-vs-permanent), it is simply absent for now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gaia.services.workspace_service import WorkspaceAccessError, resolve_within_workspace
from gaia.tools.base import RiskLevel, Tool, ToolResult

MAX_READ_BYTES = 200_000
MAX_WRITE_BYTES = 1_000_000
MAX_LISTING_ENTRIES = 500


class FilesystemReadTool(Tool):
    name = "filesystem_read"
    description = (
        "Read a file's contents or list a directory, within an explicitly allowed "
        "workspace root. Files must be UTF-8 text under 200 KB. The path must be "
        "absolute."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to a file or directory."}
        },
        "required": ["path"],
    }
    risk_level = RiskLevel.SAFE

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("path")
        if not isinstance(raw_path, str):
            return ToolResult(ok=False, content="", error="'path' must be a string")

        try:
            resolved = resolve_within_workspace(raw_path)
        except WorkspaceAccessError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        try:
            if not resolved.exists():
                return ToolResult(ok=False, content="", error=f"'{raw_path}' does not exist")

            if resolved.is_dir():
                return self._list_directory(resolved)
            return self._read_file(resolved)
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"could not read '{raw_path}': {exc}")
        except Exception as exc:  # backstop — must never raise past here
            return ToolResult(ok=False, content="", error=f"unexpected error: {exc}")

    @staticmethod
    def _list_directory(resolved: Path) -> ToolResult:
        all_entries = sorted(resolved.iterdir(), key=lambda p: p.name)
        truncated = len(all_entries) > MAX_LISTING_ENTRIES
        entries = all_entries[:MAX_LISTING_ENTRIES]
        listing = [
            {
                "name": e.name,
                "type": "dir" if e.is_dir() else "file",
                "size": e.stat().st_size if e.is_file() else None,
            }
            for e in entries
        ]
        lines = [f"{'d' if e['type'] == 'dir' else 'f'}  {e['name']}" for e in listing]
        if truncated:
            lines.append(f"…[{len(all_entries) - MAX_LISTING_ENTRIES} more entries not shown]")
        return ToolResult(
            ok=True,
            content="\n".join(lines),
            display={"path": str(resolved), "kind": "directory", "entries": listing},
        )

    @staticmethod
    def _read_file(resolved: Path) -> ToolResult:
        size = resolved.stat().st_size
        if size > MAX_READ_BYTES:
            return ToolResult(
                ok=False,
                content="",
                error=f"file is {size} bytes, over the {MAX_READ_BYTES}-byte limit",
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(ok=False, content="", error="file is not UTF-8 text")
        return ToolResult(
            ok=True, content=text, display={"path": str(resolved), "kind": "file", "size": size}
        )


class FilesystemWriteTool(Tool):
    name = "filesystem_write"
    description = (
        "Write or append text to a file within an explicitly allowed, writable "
        "workspace root. The containing directory must already exist. The path "
        "must be absolute. Content is capped at 1 MB."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file to write."},
            "content": {"type": "string", "description": "Text content to write."},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "'overwrite' (default) replaces the file; 'append' adds to the end.",
            },
        },
        "required": ["path", "content"],
    }
    risk_level = RiskLevel.CONFIRM

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw_path = arguments.get("path")
        content = arguments.get("content")
        mode = arguments.get("mode", "overwrite")

        if not isinstance(raw_path, str):
            return ToolResult(ok=False, content="", error="'path' must be a string")
        if not isinstance(content, str):
            return ToolResult(ok=False, content="", error="'content' must be a string")
        if mode not in ("overwrite", "append"):
            return ToolResult(ok=False, content="", error="'mode' must be 'overwrite' or 'append'")
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return ToolResult(
                ok=False, content="", error=f"content exceeds the {MAX_WRITE_BYTES}-byte limit"
            )

        try:
            resolved = resolve_within_workspace(raw_path, require_writable=True)
        except WorkspaceAccessError as exc:
            return ToolResult(ok=False, content="", error=str(exc))

        if not resolved.parent.exists():
            return ToolResult(
                ok=False, content="", error=f"the directory '{resolved.parent}' does not exist"
            )

        try:
            file_mode = "a" if mode == "append" else "w"
            with open(resolved, file_mode, encoding="utf-8") as handle:
                handle.write(content)
            size = resolved.stat().st_size
        except OSError as exc:
            return ToolResult(ok=False, content="", error=f"could not write '{raw_path}': {exc}")
        except Exception as exc:  # backstop — must never raise past here
            return ToolResult(ok=False, content="", error=f"unexpected error: {exc}")

        return ToolResult(
            ok=True,
            content=f"wrote {len(content)} characters to {resolved} ({mode})",
            display={
                "path": str(resolved),
                "mode": mode,
                "bytes_written": len(content.encode("utf-8")),
                "file_size": size,
            },
        )
