"""Runtime configuration and on-disk layout for GAIA.

Two rules govern this module:

1. **User data never lives in the source repository.** Everything GAIA writes
   goes under a single data directory outside the checkout (see `data_dir`).
2. **Secrets never live in the database or in git.** API keys are resolved from
   the OS keyring or the environment (see `gaia.core.secrets`).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# A .env sitting next to the backend package is convenient in development. In a
# packaged desktop build there is normally no .env at all and every value comes
# from defaults plus the settings stored in the database.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_ROOT / ".env", override=False)


def _default_data_dir() -> Path:
    """Platform-appropriate data directory.

    Linux   ~/.local/share/GAIA
    macOS   ~/Library/Application Support/GAIA
    Windows %LOCALAPPDATA%\\GAIA
    """
    return Path(user_data_dir(appname="GAIA", appauthor=False, roaming=False))


class Settings(BaseSettings):
    """Process-level configuration, sourced from environment variables.

    Anything a user is expected to change from inside the app lives in the
    `settings` table instead (see `gaia.services.settings_service`); this class
    only holds what has to be known before the database is open.
    """

    model_config = SettingsConfigDict(env_prefix="GAIA_", extra="ignore")

    data_dir: Path = Field(default_factory=_default_data_dir)
    host: str = "127.0.0.1"
    port: int = 8756
    log_level: str = "INFO"

    # Comma-separated extra origins allowed to call the API. The Tauri shell
    # loads the UI from `tauri://localhost` / `http://localhost` so those are
    # always permitted; this is for custom dev setups.
    extra_cors_origins: str = ""

    # The mock provider returns canned text and is *not* a language model. It
    # exists so the test-suite and CI can exercise the streaming path offline.
    # It is hidden from the UI unless this flag is set.
    enable_mock_provider: bool = False

    # Set by the Tauri shell so the backend can shut itself down if the desktop
    # process disappears.
    parent_pid: int | None = None

    @property
    def database_dir(self) -> Path:
        return self.data_dir / "database"

    @property
    def database_path(self) -> Path:
        return self.database_dir / "gaia.db"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path}"

    @property
    def async_database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def experiments_dir(self) -> Path:
        return self.data_dir / "experiments"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def sandbox_dir(self) -> Path:
        return self.data_dir / "sandbox"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def cors_origins(self) -> list[str]:
        origins = [
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            f"http://{self.host}:{self.port}",
        ]
        origins += [o.strip() for o in self.extra_cors_origins.split(",") if o.strip()]
        return origins

    def ensure_directories(self) -> None:
        """Create the data layout. Safe to call repeatedly."""
        for directory in (
            self.data_dir,
            self.database_dir,
            self.logs_dir,
            self.documents_dir,
            self.projects_dir,
            self.experiments_dir,
            self.memory_dir,
            self.sandbox_dir,
            self.config_dir,
            self.backups_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        # The data directory holds conversations, memory and credentials-adjacent
        # material. Keep it owner-only where the platform supports it.
        if os.name == "posix":
            try:
                self.data_dir.chmod(0o700)
            except OSError:  # pragma: no cover - unusual filesystems
                pass


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that point GAIA at a temporary data directory."""
    get_settings.cache_clear()
