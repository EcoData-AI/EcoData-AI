"""Schema migrations.

Alembic owns the schema. The app runs `upgrade head` at startup so a desktop
user never has to run a migration command by hand — the first launch after an
update just works.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from gaia.config import get_settings

logger = logging.getLogger("gaia.db")

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    return config


def upgrade_database() -> None:
    settings = get_settings()
    settings.ensure_directories()
    logger.info("running migrations", extra={"database": str(settings.database_path)})
    command.upgrade(alembic_config(), "head")
