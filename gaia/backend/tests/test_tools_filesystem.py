"""Filesystem tools: containment, read, write, and the workspace_service CRUD
that grants them anywhere to operate at all.

Every test needs `gaia_env` (directly, or via `session`) — both the tools and
`workspace_service` open real database sessions.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from gaia.services import workspace_service
from gaia.services.workspace_service import WorkspaceRootError
from gaia.tools.base import RiskLevel
from gaia.tools.filesystem import FilesystemReadTool, FilesystemWriteTool


def test_read_tool_is_safe_and_write_tool_is_confirm():
    assert FilesystemReadTool.risk_level is RiskLevel.SAFE
    assert FilesystemWriteTool.risk_level is RiskLevel.CONFIRM


# --------------------------------------------------------------- workspace_service


def test_add_root_requires_absolute_path(session):
    with pytest.raises(WorkspaceRootError, match="absolute"):
        workspace_service.add_root(session, path="relative/dir", writable=False)


def test_add_root_requires_existing_directory(session, tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(WorkspaceRootError, match="does not exist"):
        workspace_service.add_root(session, path=str(missing), writable=False)


def test_add_root_rejects_a_file(session, tmp_path):
    file_path = tmp_path / "a_file.txt"
    file_path.write_text("hi")
    with pytest.raises(WorkspaceRootError, match="not a directory"):
        workspace_service.add_root(session, path=str(file_path), writable=False)


def test_add_root_rejects_filesystem_root(session, tmp_path):
    fs_root = tmp_path.anchor  # e.g. "C:\\" on Windows, "/" on POSIX
    with pytest.raises(WorkspaceRootError, match="filesystem root"):
        workspace_service.add_root(session, path=fs_root, writable=False)


def test_add_root_rejects_duplicates(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=False)
    with pytest.raises(WorkspaceRootError, match="already a workspace root"):
        workspace_service.add_root(session, path=str(tmp_path), writable=False)


def test_add_list_remove_root_roundtrip(session, tmp_path):
    root = workspace_service.add_root(session, path=str(tmp_path), writable=True)
    assert root.writable is True
    assert root.enabled is True

    roots = workspace_service.list_roots(session)
    assert any(r.id == root.id for r in roots)

    assert workspace_service.remove_root(session, root.id) is True
    assert workspace_service.remove_root(session, root.id) is False
    assert all(r.id != root.id for r in workspace_service.list_roots(session))


# --------------------------------------------------------------- filesystem_read


async def test_read_rejects_relative_path(session):
    tool = FilesystemReadTool()
    result = await tool.execute({"path": "relative.txt"})
    assert result.ok is False
    assert "absolute" in (result.error or "")


async def test_read_with_no_workspace_roots_configured(session, tmp_path):
    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(tmp_path / "whatever.txt")})
    assert result.ok is False
    assert "No workspace roots are configured" in (result.error or "")


async def test_read_file_within_root(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=False)
    target = tmp_path / "note.txt"
    target.write_text("hello from the workspace")

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(target)})
    assert result.ok is True
    assert result.content == "hello from the workspace"
    assert result.display["kind"] == "file"


async def test_read_directory_listing(session, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=False)
    (workspace / "a.txt").write_text("a")
    (workspace / "sub").mkdir()

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(workspace)})
    assert result.ok is True
    names = {e["name"] for e in result.display["entries"]}
    assert names == {"a.txt", "sub"}


async def test_read_rejects_path_outside_any_root(session, tmp_path):
    inside = tmp_path / "workspace"
    inside.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("should not be readable")
    workspace_service.add_root(session, path=str(inside), writable=False)

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(outside)})
    assert result.ok is False
    assert "not inside any allowed workspace" in (result.error or "")


async def test_read_rejects_traversal_escape(session, tmp_path):
    inside = tmp_path / "workspace"
    inside.mkdir()
    (tmp_path / "secret.txt").write_text("nope")
    workspace_service.add_root(session, path=str(inside), writable=False)

    escape_path = str(inside / ".." / "secret.txt")
    tool = FilesystemReadTool()
    result = await tool.execute({"path": escape_path})
    assert result.ok is False
    assert "not inside any allowed workspace" in (result.error or "")


async def test_read_missing_file(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=False)
    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(tmp_path / "nope.txt")})
    assert result.ok is False
    assert "does not exist" in (result.error or "")


async def test_read_rejects_oversized_file(session, tmp_path, monkeypatch):
    import gaia.tools.filesystem as fs_module

    monkeypatch.setattr(fs_module, "MAX_READ_BYTES", 10)
    workspace_service.add_root(session, path=str(tmp_path), writable=False)
    big = tmp_path / "big.txt"
    big.write_text("x" * 100)

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(big)})
    assert result.ok is False
    assert "limit" in (result.error or "")


async def test_read_rejects_missing_path_argument(session):
    tool = FilesystemReadTool()
    result = await tool.execute({})
    assert result.ok is False


async def test_read_rejects_symlink_escape(session, tmp_path):
    """A symlink inside the workspace pointing outside it must not grant
    access: `Path.resolve()` follows the symlink before the containment
    check runs, so the escape is caught regardless of the link itself being
    "inside" the root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("should not be readable via a symlink")
    workspace_service.add_root(session, path=str(workspace), writable=False)

    link = workspace / "escape_link.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("creating symlinks needs elevated privileges or Developer Mode here")

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(link)})
    assert result.ok is False
    assert "not inside any allowed workspace" in (result.error or "")


async def test_read_rejects_junction_escape(session, tmp_path):
    """Windows directory junctions are a distinct mechanism from symlinks and
    do not require elevated privileges to create — a realistic escape vector
    on this platform that a symlink-only test would miss."""
    if os.name != "nt":
        pytest.skip("directory junctions are a Windows-specific feature")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_dir = tmp_path / "secret_dir"
    secret_dir.mkdir()
    (secret_dir / "secret.txt").write_text("nope")
    workspace_service.add_root(session, path=str(workspace), writable=False)

    junction = workspace / "escape_junction"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(secret_dir)],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"could not create a junction on this machine: {completed.stderr}")

    tool = FilesystemReadTool()
    result = await tool.execute({"path": str(junction / "secret.txt")})
    assert result.ok is False
    assert "not inside any allowed workspace" in (result.error or "")


async def test_read_rejects_different_drive_letter(session, tmp_path):
    """A path on a different drive than any workspace root is an explicit,
    named case of "outside any allowed root" — mechanically the same check
    as any other escape, but worth its own test for documentation value."""
    if os.name != "nt":
        pytest.skip("drive letters are a Windows-specific concept")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=False)

    other_drive = "D:\\" if str(workspace)[0].upper() != "D" else "E:\\"
    tool = FilesystemReadTool()
    result = await tool.execute({"path": other_drive + "Windows\\System32\\drivers\\etc\\hosts"})
    assert result.ok is False


# --------------------------------------------------------------- filesystem_write


async def test_write_rejects_readonly_root(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=False)
    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(tmp_path / "out.txt"), "content": "hi"})
    assert result.ok is False
    assert "read-only" in (result.error or "")
    assert not (tmp_path / "out.txt").exists()


async def test_write_creates_and_overwrites_file(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    target = tmp_path / "out.txt"

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(target), "content": "first"})
    assert result.ok is True
    assert target.read_text() == "first"

    result2 = await tool.execute({"path": str(target), "content": "second", "mode": "overwrite"})
    assert result2.ok is True
    assert target.read_text() == "second"


async def test_write_append_mode(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    target = tmp_path / "log.txt"
    target.write_text("line1\n")

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(target), "content": "line2\n", "mode": "append"})
    assert result.ok is True
    assert target.read_text() == "line1\nline2\n"


async def test_write_rejects_path_outside_root(session, tmp_path):
    inside = tmp_path / "workspace"
    inside.mkdir()
    workspace_service.add_root(session, path=str(inside), writable=True)

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(tmp_path / "escape.txt"), "content": "no"})
    assert result.ok is False
    assert not (tmp_path / "escape.txt").exists()


async def test_write_rejects_missing_parent_directory(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    tool = FilesystemWriteTool()
    result = await tool.execute(
        {"path": str(tmp_path / "no_such_dir" / "out.txt"), "content": "x"}
    )
    assert result.ok is False
    assert "does not exist" in (result.error or "")


async def test_write_rejects_oversized_content(session, tmp_path, monkeypatch):
    import gaia.tools.filesystem as fs_module

    monkeypatch.setattr(fs_module, "MAX_WRITE_BYTES", 5)
    workspace_service.add_root(session, path=str(tmp_path), writable=True)

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(tmp_path / "out.txt"), "content": "way too long"})
    assert result.ok is False
    assert "limit" in (result.error or "")


async def test_write_rejects_invalid_mode(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    tool = FilesystemWriteTool()
    result = await tool.execute(
        {"path": str(tmp_path / "out.txt"), "content": "x", "mode": "delete"}
    )
    assert result.ok is False
    assert "mode" in (result.error or "")


async def test_write_mode_delete_cannot_touch_an_existing_file(session, tmp_path):
    """Belt-and-suspenders on top of test_write_rejects_invalid_mode: prove a
    'delete'-mode request doesn't just get rejected, it genuinely leaves an
    existing file untouched."""
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    target = tmp_path / "existing.txt"
    target.write_text("keep me")

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(target), "content": "x", "mode": "delete"})
    assert result.ok is False
    assert target.read_text() == "keep me"


async def test_write_rejects_missing_required_arguments(session):
    tool = FilesystemWriteTool()
    result = await tool.execute({})
    assert result.ok is False


async def test_write_over_a_directory_fails_cleanly(session, tmp_path):
    workspace_service.add_root(session, path=str(tmp_path), writable=True)
    a_directory = tmp_path / "im_a_directory"
    a_directory.mkdir()

    tool = FilesystemWriteTool()
    result = await tool.execute({"path": str(a_directory), "content": "x"})
    assert result.ok is False
    assert a_directory.is_dir()  # untouched, and the tool didn't raise


def test_no_delete_tool_is_registered():
    """Deletion is BLOCKED-tier per docs/SECURITY.md's risk table and is not
    implemented at all — not a registered tool, and filesystem_write's `mode`
    enum has no delete-like option for a compromised prompt to discover."""
    from gaia.tools.registry import TOOL_CLASSES

    assert not any("delete" in name.lower() for name in TOOL_CLASSES)
    assert "delete" not in FilesystemWriteTool.parameters["properties"]["mode"]["enum"]
