from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Both must be set before `gaia.config` is imported anywhere, so that the cached
# Settings object points at the temporary directory and the mock provider is
# selectable. Session-scoped fixtures run too late for this.
_TMP_ROOT = Path(os.environ.setdefault("GAIA_TEST_ROOT", "/tmp/gaia-tests"))
os.environ.setdefault("GAIA_ENABLE_MOCK_PROVIDER", "1")


@pytest.fixture()
def gaia_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point GAIA at a throwaway data directory with a migrated database."""
    from gaia.config import get_settings, reset_settings_cache
    from gaia.db import session as db_session
    from gaia.db.migrations import upgrade_database

    data_dir = tmp_path / "data"
    monkeypatch.setenv("GAIA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("GAIA_ENABLE_MOCK_PROVIDER", "1")
    # Keys must never be read from the developer's real environment during tests.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    reset_settings_cache()
    db_session.dispose_engine()

    get_settings().ensure_directories()
    upgrade_database()

    yield data_dir

    db_session.dispose_engine()
    reset_settings_cache()


@pytest.fixture()
def session(gaia_env: Path):
    from gaia.db.session import get_session_factory

    with get_session_factory()() as db:
        yield db


@pytest.fixture()
def client(gaia_env: Path):
    from fastapi.testclient import TestClient

    from gaia.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def mock_client(client):
    """A client whose active provider is the offline mock."""
    response = client.patch(
        "/api/settings",
        json={"values": {"llm.active_provider": "mock", "llm.active_model": "mock-echo"}},
    )
    assert response.status_code == 200
    return client
