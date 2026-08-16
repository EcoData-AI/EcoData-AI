"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gaia import APP_TAGLINE, __version__
from gaia.api import chat, conversations, providers, system
from gaia.config import get_settings
from gaia.core.logging_setup import configure_logging
from gaia.db.migrations import upgrade_database
from gaia.db.session import dispose_engine

logger = logging.getLogger("gaia")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()
    configure_logging()
    upgrade_database()
    logger.info("GAIA backend started", extra={"data_dir": str(settings.data_dir)})
    try:
        yield
    finally:
        dispose_engine()
        logger.info("GAIA backend stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GAIA",
        description=APP_TAGLINE,
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system.router)
    app.include_router(conversations.router)
    app.include_router(chat.router)
    app.include_router(providers.router)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Never show a raw traceback to the user (spec §57)."""
        logger.exception("unhandled request error", extra={"path": request.url.path})
        return JSONResponse(
            status_code=500,
            content={
                "detail": "GAIA hit an unexpected problem. The details were written to the log.",
            },
        )

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the built UI when it exists.

    In development the UI is served by Vite on :5173 and this is a no-op. In a
    packaged build the Tauri shell loads its own bundled assets, so this mainly
    serves the "run GAIA without the desktop shell" fallback path.
    """
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # Any non-API path falls through to the SPA entry point so client-side
        # routing works on a hard refresh.
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
