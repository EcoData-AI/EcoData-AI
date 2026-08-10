from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from gaia import __version__
from gaia.config import get_settings
from gaia.core.capabilities import CAPABILITIES
from gaia.db.session import get_engine, get_session
from gaia.llm.registry import build_active_provider
from gaia.schemas.api import (
    CapabilityOut,
    ComponentStatus,
    PrivacyRow,
    SettingsOut,
    SettingsUpdate,
    SystemStatus,
)
from gaia.services import settings_service

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness probe. The desktop shell polls this before showing the window."""
    return {"status": "ok", "version": __version__}


@router.get("/capabilities", response_model=list[CapabilityOut])
def capabilities() -> list[CapabilityOut]:
    return [CapabilityOut(**asdict(c)) for c in CAPABILITIES]


@router.get("/system/status", response_model=SystemStatus)
async def system_status(session: Session = Depends(get_session)) -> SystemStatus:
    settings = get_settings()
    components: list[ComponentStatus] = [
        ComponentStatus(
            name="GAIA Core",
            state="ok",
            detail=f"v{__version__} on Python {platform.python_version()}",
        )
    ]

    try:
        session.execute(text("SELECT 1"))
        size = settings.database_path.stat().st_size if settings.database_path.exists() else 0
        components.append(
            ComponentStatus(name="Database", state="ok", detail=f"SQLite, {size / 1024:.0f} KB")
        )
    except Exception as exc:
        components.append(ComponentStatus(name="Database", state="error", detail=str(exc)))

    provider_id = settings_service.get_active_provider_id(session)
    model_id = settings_service.get(session, settings_service.ACTIVE_MODEL)
    try:
        provider = build_active_provider(session)
        provider_health = await provider.health()
        components.append(
            ComponentStatus(
                name="LLM",
                state=provider_health.state.value,
                detail=f"{provider.display_name}: {provider_health.detail}",
            )
        )
    except Exception as exc:
        components.append(ComponentStatus(name="LLM", state="error", detail=str(exc)))

    # Everything else is reported as "not_built" rather than silently omitted,
    # so the panel never implies a capability that does not exist yet.
    for capability in CAPABILITIES:
        if capability.key in {"chat", "history", "providers", "settings", "backups"}:
            continue
        components.append(
            ComponentStatus(
                name=capability.label,
                state="not_built",
                detail=f"Planned for Milestone {capability.milestone}",
            )
        )

    return SystemStatus(
        version=__version__,
        components=components,
        data_dir=str(settings.data_dir),
        active_provider=provider_id,
        active_model=model_id,
    )


@router.get("/privacy", response_model=list[PrivacyRow])
def privacy(session: Session = Depends(get_session)) -> list[PrivacyRow]:
    """Where each category of data lives. Must stay truthful as features land."""
    provider_id = settings_service.get_active_provider_id(session)
    from gaia.llm.registry import PROVIDER_CLASSES

    provider_cls = PROVIDER_CLASSES.get(provider_id)
    llm_local = bool(provider_cls and provider_cls.is_local)

    return [
        PrivacyRow(
            label="Conversation storage",
            location="LOCAL",
            detail="SQLite file in your GAIA data directory.",
        ),
        PrivacyRow(label="Settings", location="LOCAL", detail="Same local database."),
        PrivacyRow(
            label="API keys",
            location="LOCAL",
            detail="OS keyring, or an owner-only file. Never in the database or in git.",
        ),
        PrivacyRow(
            label="LLM inference",
            location="LOCAL" if llm_local else "CLOUD",
            detail=(
                f"{provider_cls.display_name if provider_cls else provider_id} — "
                + (
                    "runs on this machine; nothing leaves it."
                    if llm_local
                    else "your message text and conversation history are sent to this provider."
                )
            ),
        ),
        PrivacyRow(
            label="Memory", location="NOT BUILT", detail="Planned for Milestone 3. Will be local."
        ),
        PrivacyRow(
            label="Documents",
            location="NOT BUILT",
            detail="Planned for Milestone 4. Will be local.",
        ),
        PrivacyRow(
            label="Python execution",
            location="NOT BUILT",
            detail="Planned for Milestone 2. Will run in a local sandbox.",
        ),
        PrivacyRow(
            label="Web search",
            location="NOT BUILT",
            detail="Planned for Milestone 6. Will be external and clearly marked.",
        ),
        PrivacyRow(
            label="Telemetry",
            location="LOCAL",
            detail="GAIA collects no analytics and phones home to nobody.",
        ),
    ]


@router.get("/settings", response_model=SettingsOut)
def read_settings(session: Session = Depends(get_session)) -> SettingsOut:
    return SettingsOut(
        values=settings_service.all_settings(session), data_dir=str(get_settings().data_dir)
    )


@router.patch("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdate, session: Session = Depends(get_session)
) -> SettingsOut:
    unknown = set(payload.values) - set(settings_service.DEFAULTS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {sorted(unknown)}")
    for key, value in payload.values.items():
        settings_service.set_value(session, key, value)
    session.commit()
    return read_settings(session)


@router.post("/backup/export")
def export_backup() -> FileResponse:
    """Write a consistent snapshot of the database and hand it back for download.

    Uses SQLite's own backup API rather than copying the file, so it is safe to
    run while GAIA is in use (a plain copy can catch a half-written WAL).
    """
    import sqlite3

    settings = get_settings()
    settings.ensure_directories()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = settings.backups_dir / f"gaia-backup-{stamp}.db"

    source = sqlite3.connect(settings.database_path)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    finally:
        source.close()
        destination.close()

    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


@router.post("/backup/import")
async def import_backup(file: UploadFile) -> dict:
    """Replace the live database with an uploaded backup.

    The current database is copied aside first, so an import can be undone.
    """
    settings = get_settings()
    settings.ensure_directories()

    payload = await file.read()
    if not payload.startswith(b"SQLite format 3\x00"):
        raise HTTPException(
            status_code=400,
            detail="That file is not a SQLite database. Choose a file exported by GAIA.",
        )

    staging = settings.backups_dir / "import-staging.db"
    staging.write_bytes(payload)

    # Verify before destroying anything.
    import sqlite3

    try:
        connection = sqlite3.connect(staging)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        connection.close()
    except sqlite3.DatabaseError as exc:
        staging.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Unreadable database: {exc}") from exc

    if "conversations" not in tables or "messages" not in tables:
        staging.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail="That database does not look like a GAIA backup."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rollback = settings.backups_dir / f"pre-import-{stamp}.db"

    from gaia.db.session import dispose_engine

    get_engine()  # ensure the engine exists before disposing it
    dispose_engine()

    if settings.database_path.exists():
        shutil.copy2(settings.database_path, rollback)
    # WAL and shared-memory sidecars belong to the old database.
    for suffix in ("-wal", "-shm"):
        Path(str(settings.database_path) + suffix).unlink(missing_ok=True)

    shutil.move(str(staging), settings.database_path)

    return {
        "status": "imported",
        "previous_database_saved_to": str(rollback) if rollback.exists() else None,
        "restart_required": True,
    }


@router.get("/system/info")
def system_info() -> dict:
    settings = get_settings()
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()}",
        "data_dir": str(settings.data_dir),
        "database": str(settings.database_path),
        "logs": str(settings.logs_dir),
    }
