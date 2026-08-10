"""End-to-end chat: streaming, persistence, titling, and honest failure."""

from __future__ import annotations

import json


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, json.loads(line[6:])))
            name = None
    return events


def run_turn(client, conversation_id: str, content: str) -> list[tuple[str, dict]]:
    with client.stream(
        "POST", "/api/chat", json={"conversation_id": conversation_id, "content": content}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_sse("".join(response.iter_text()))


def test_stream_emits_deltas_and_completes(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    events = run_turn(mock_client, conversation_id, "Explain Nash equilibrium")

    names = [name for name, _ in events]
    assert names[0] == "user_message"
    assert "start" in names
    assert names.count("delta") > 1  # actually streamed, not one lump
    assert names[-1] == "done"

    text = "".join(data["text"] for name, data in events if name == "delta")
    assert "Explain Nash equilibrium" in text

    done = next(data for name, data in events if name == "done")
    assert done["output_tokens"] is not None
    assert done["latency_ms"] >= 0


def test_messages_persist_and_survive_reload(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    run_turn(mock_client, conversation_id, "first question")
    run_turn(mock_client, conversation_id, "second question")

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert [m["sequence"] for m in messages] == [1, 2, 3, 4]
    assert all(m["status"] == "complete" for m in messages)
    assert messages[0]["content"] == "first question"
    assert messages[1]["content"].strip().startswith("[mock provider]")


def test_first_message_titles_the_conversation(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    assert mock_client.get(f"/api/conversations/{conversation_id}").json()["title"] == (
        "New conversation"
    )

    run_turn(mock_client, conversation_id, "How do I model an oligopoly?")

    title = mock_client.get(f"/api/conversations/{conversation_id}").json()["title"]
    assert title == "How do I model an oligopoly?"


def test_long_first_message_title_is_truncated(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    run_turn(mock_client, conversation_id, "word " * 60)
    title = mock_client.get(f"/api/conversations/{conversation_id}").json()["title"]
    assert len(title) <= 60
    assert title.endswith("…")


def test_unknown_conversation_yields_error_event(mock_client):
    events = run_turn(mock_client, "no-such-conversation", "hello")
    assert events == [("error", {"kind": "not_found", "message": events[0][1]["message"]})]


def test_unconfigured_provider_reports_instead_of_faking(client):
    """With no API key set, GAIA must say so — never invent a reply."""
    client.patch("/api/settings", json={"values": {"llm.active_provider": "anthropic"}})
    conversation_id = client.post("/api/conversations", json={}).json()["id"]

    events = run_turn(client, conversation_id, "hello")
    names = [name for name, _ in events]

    assert "delta" not in names
    error = next(data for name, data in events if name == "error")
    assert error["kind"] == "not_configured"
    assert "key" in error["message"].lower()
    assert error["remedy"]


def test_empty_message_is_rejected(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    response = mock_client.post(
        "/api/chat", json={"conversation_id": conversation_id, "content": ""}
    )
    assert response.status_code == 422
