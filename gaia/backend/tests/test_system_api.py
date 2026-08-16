from __future__ import annotations

from gaia.core.capabilities import CAPABILITIES


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["version"]


def test_settings_roundtrip_and_validation(client):
    values = client.get("/api/settings").json()["values"]
    assert values["llm.active_provider"] == "anthropic"

    updated = client.patch(
        "/api/settings", json={"values": {"general.custom_instructions": "Be terse."}}
    )
    assert updated.status_code == 200
    assert updated.json()["values"]["general.custom_instructions"] == "Be terse."

    rejected = client.patch("/api/settings", json={"values": {"not.a.real.setting": 1}})
    assert rejected.status_code == 400


def test_capabilities_are_reported_honestly(client):
    capabilities = {c["key"]: c for c in client.get("/api/capabilities").json()}

    assert capabilities["chat"]["available"] is True
    assert capabilities["history"]["available"] is True
    # Milestone 2's first step: Calculator is live, so the tool system itself
    # is no longer claimed as unbuilt — but nothing built on top of it is.
    assert capabilities["tools"]["available"] is True

    # None of these ship yet; the API must not claim otherwise.
    for key in ("python", "memory", "research", "voice", "simulation"):
        assert capabilities[key]["available"] is False
        assert capabilities[key]["milestone"] > 1


def test_capability_keys_are_unique():
    keys = [c.key for c in CAPABILITIES]
    assert len(keys) == len(set(keys))


def test_system_status_marks_unbuilt_components(client):
    body = client.get("/api/system/status").json()
    names = {c["name"]: c["state"] for c in body["components"]}

    assert names["GAIA Core"] == "ok"
    assert names["Database"] == "ok"
    # With no API key configured, the LLM must not report "ok".
    assert names["LLM"] in {"not_configured", "error"}
    assert names["Python sandbox"] == "not_built"
    assert names["Voice"] == "not_built"


def test_system_status_reports_a_built_capability_as_ok(client):
    # A capability that is `available` in core/capabilities.py must not also
    # report "not_built" here — that would be the exact inconsistency the
    # honesty constraint (docs/ARCHITECTURE.md) exists to prevent.
    body = client.get("/api/system/status").json()
    names = {c["name"]: c["state"] for c in body["components"]}
    assert names["Tool system"] == "ok"


def test_privacy_dashboard_marks_cloud_inference(client):
    rows = {row["label"]: row for row in client.get("/api/privacy").json()}

    assert rows["Conversation storage"]["location"] == "LOCAL"
    assert rows["API keys"]["location"] == "LOCAL"
    assert rows["LLM inference"]["location"] == "CLOUD"  # anthropic is the default

    client.patch("/api/settings", json={"values": {"llm.active_provider": "ollama"}})
    rows = {row["label"]: row for row in client.get("/api/privacy").json()}
    assert rows["LLM inference"]["location"] == "LOCAL"


def test_backup_export_produces_a_sqlite_file(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={"title": "keep me"}).json()["id"]
    assert conversation_id

    response = mock_client.post("/api/backup/export")
    assert response.status_code == 200
    assert response.content.startswith(b"SQLite format 3\x00")


def test_backup_import_rejects_non_database_files(client):
    response = client.post(
        "/api/backup/import", files={"file": ("notes.txt", b"just some text", "text/plain")}
    )
    assert response.status_code == 400
    assert "SQLite" in response.json()["detail"]
