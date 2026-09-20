"""Workspace root management — the directories a tool may touch.

A root grants no capability by itself; `resolve_within_workspace` below is
what actually enforces containment against these rows at execution time, used
by every workspace-scoped tool (`gaia/tools/filesystem.py`, `terminal.py`).
CRUD (`list_roots`/`add_root`/`remove_root`) is the same shape as
`conversation_service.py`.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.models import WorkspaceRoot
from gaia.db.session import session_scope


class WorkspaceRootError(ValueError):
    """A workspace root could not be added as requested."""


class WorkspaceAccessError(ValueError):
    """A path is outside every enabled workspace root, or the root disallows it."""


def list_roots(session: Session) -> list[WorkspaceRoot]:
    stmt = select(WorkspaceRoot).order_by(WorkspaceRoot.created_at)
    return list(session.execute(stmt).scalars().all())


def add_root(session: Session, *, path: str, writable: bool) -> WorkspaceRoot:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        raise WorkspaceRootError("Workspace root must be an absolute path.")
    if not expanded.exists():
        raise WorkspaceRootError(f"'{expanded}' does not exist.")
    if not expanded.is_dir():
        raise WorkspaceRootError(f"'{expanded}' is not a directory.")

    resolved = expanded.resolve()
    # A filesystem root's own parent is itself — this rejects "C:\", "/", and
    # similar. Granting one of those would make "workspace-scoped" meaningless,
    # and is almost certainly a mistake rather than something anyone intends.
    if resolved.parent == resolved:
        raise WorkspaceRootError(
            f"'{resolved}' is a filesystem root; choose a specific directory instead."
        )
    canonical = str(resolved)

    existing = session.execute(
        select(WorkspaceRoot).where(WorkspaceRoot.path == canonical)
    ).scalar_one_or_none()
    if existing is not None:
        raise WorkspaceRootError(f"'{canonical}' is already a workspace root.")

    root = WorkspaceRoot(path=canonical, writable=writable, enabled=True)
    session.add(root)
    session.commit()
    session.refresh(root)
    return root


def remove_root(session: Session, root_id: str) -> bool:
    root = session.get(WorkspaceRoot, root_id)
    if root is None:
        return False
    session.delete(root)
    session.commit()
    return True


def _enabled_roots() -> list[WorkspaceRoot]:
    with session_scope() as session:
        return list(
            session.execute(
                select(WorkspaceRoot).where(WorkspaceRoot.enabled.is_(True))
            ).scalars().all()
        )


def resolve_within_workspace(raw_path: str, *, require_writable: bool = False) -> Path:
    """Canonicalise `raw_path` and verify it falls inside an enabled, allowed root.

    Used by every workspace-scoped tool. Never resolve containment by string
    or prefix matching on the raw path — `..` and symlinks defeat that; this
    canonicalises first (`Path.resolve`, which collapses both) and only then
    checks containment.
    """
    if not raw_path or not raw_path.strip():
        raise WorkspaceAccessError("path must not be empty")
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise WorkspaceAccessError("path must be absolute")

    # strict=False: the target need not exist yet (a write, or a command about
    # to create something), but every `..` and every existing symlink along
    # the way is still resolved for real — this is what makes a traversal
    # attempt resolve to where it actually points before containment is checked.
    resolved = candidate.resolve(strict=False)

    roots = _enabled_roots()
    if not roots:
        raise WorkspaceAccessError(
            "No workspace roots are configured, so no directory is accessible yet."
        )

    for root in roots:
        root_path = Path(root.path).resolve(strict=False)
        try:
            resolved.relative_to(root_path)
        except ValueError:
            continue
        if require_writable and not root.writable:
            raise WorkspaceAccessError(f"'{root.path}' is configured read-only.")
        return resolved

    raise WorkspaceAccessError(f"'{raw_path}' is not inside any allowed workspace root.")
