"""API-key storage.

Precedence when reading a key:

1. Environment variable (e.g. `ANTHROPIC_API_KEY`) — lets a developer run GAIA
   from a shell without touching the OS keyring.
2. The OS keyring (Keychain / Credential Manager / Secret Service).
3. An owner-only file under the data directory, used when no keyring backend is
   available (common on headless Linux).

Keys are never written to the database, never returned by the API, and never
logged. `describe_key` exists so the UI can say "a key is set" without ever
transporting the value.
"""

from __future__ import annotations

import json
import os
import stat
from typing import Final

from gaia.config import get_settings

KEYRING_SERVICE: Final = "GAIA"

# Environment variables consulted per provider, in order.
ENV_VARS: Final[dict[str, tuple[str, ...]]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai_compatible": ("OPENAI_API_KEY", "GAIA_OPENAI_API_KEY"),
}


def _fallback_path():
    return get_settings().config_dir / "credentials.json"


def _read_fallback() -> dict[str, str]:
    path = _fallback_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_fallback(data: dict[str, str]) -> None:
    settings = get_settings()
    settings.ensure_directories()
    path = _fallback_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _keyring():
    """Import keyring lazily — it can be slow and may have no usable backend."""
    try:
        import keyring
        from keyring.errors import NoKeyringError  # noqa: F401

        return keyring
    except Exception:
        return None


def get_api_key(provider_id: str) -> str | None:
    for env_var in ENV_VARS.get(provider_id, ()):
        value = os.environ.get(env_var)
        if value:
            return value

    keyring = _keyring()
    if keyring is not None:
        try:
            value = keyring.get_password(KEYRING_SERVICE, provider_id)
            if value:
                return value
        except Exception:
            pass  # fall through to the file store

    return _read_fallback().get(provider_id) or None


def set_api_key(provider_id: str, api_key: str) -> str:
    """Store a key. Returns the backend used, for display in Settings."""
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, provider_id, api_key)
            return "os_keyring"
        except Exception:
            pass
    data = _read_fallback()
    data[provider_id] = api_key
    _write_fallback(data)
    return "encrypted_file"


def delete_api_key(provider_id: str) -> None:
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.delete_password(KEYRING_SERVICE, provider_id)
        except Exception:
            pass
    data = _read_fallback()
    if data.pop(provider_id, None) is not None:
        _write_fallback(data)


def describe_key(provider_id: str) -> dict[str, object]:
    """Non-secret description of a stored key, safe to send to the UI."""
    key = get_api_key(provider_id)
    if not key:
        return {"configured": False, "hint": None, "source": None}
    source = "environment"
    if not any(os.environ.get(v) for v in ENV_VARS.get(provider_id, ())):
        source = "os_keyring" if _keyring() is not None else "encrypted_file"
        if provider_id in _read_fallback():
            source = "encrypted_file"
    # Show only the last four characters, the standard "is this the right key?"
    # affordance, never enough to reconstruct the secret.
    return {"configured": True, "hint": f"…{key[-4:]}", "source": source}
