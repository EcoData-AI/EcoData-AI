from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from gaia.config import get_settings
from gaia.db.base import Base
from gaia.db import models  # noqa: F401  (imported for its side effect: table registration)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL is always taken from GAIA's own settings so migrations and the app
# can never disagree about which database file they are pointing at.
_settings = get_settings()
# SQLite will not create missing parent directories, and on a first run the data
# directory does not exist yet.
_settings.ensure_directories()
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most things in place; batch mode rewrites the
            # table instead, which keeps future migrations workable.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
