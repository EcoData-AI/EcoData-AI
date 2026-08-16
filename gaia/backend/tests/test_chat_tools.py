"""End-to-end tool-call loop: the mock provider's scripted triggers exercise the
full path — SSE events, `ToolCall` audit rows, and the persisted message —
with no real provider or credentials, the same way `test_chat_stream.py`
exercises plain streaming."""

from __future__ import annotations

import json

from gaia.services.chat_service import MAX_TOOL_ITERATIONS


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
        return parse_sse("".join(response.iter_text()))


def test_calculator_call_completes_the_turn(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    events = run_turn(mock_client, conversation_id, "calc: 2 + 2")
    names = [name for name, _ in events]

    assert names[0] == "user_message"
    assert "start" in names
    assert "tool_call" in names
    assert "tool_result" in names
    assert names[-1] == "done"
    # No turn-level error: a successful tool call is not a turn failure.
    assert "error" not in names

    tool_call = next(data for name, data in events if name == "tool_call")
    assert tool_call["tool"] == "calculator"
    assert tool_call["risk_level"] == "safe"
    assert tool_call["arguments"] == {"expression": "2 + 2"}

    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["content"] == "4"
    assert tool_result["display"] == {"expression": "2 + 2", "result": "4"}

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assistant = messages[-1]
    assert assistant["role"] == "assistant"
    assert assistant["status"] == "complete"
    assert "4" in assistant["content"]
    assert assistant["extra"]["tool_calls"][0]["tool"] == "calculator"
    assert assistant["extra"]["tool_calls"][0]["ok"] is True


def test_calculator_call_is_audited(mock_client, session):
    from sqlalchemy import select

    from gaia.db.models import ToolCall

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    run_turn(mock_client, conversation_id, "calc: 6 * 7")

    rows = session.execute(select(ToolCall)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.tool_name == "calculator"
    assert row.risk_level == "safe"
    assert row.approval == "auto"
    assert row.status == "succeeded"
    assert row.arguments == {"expression": "6 * 7"}
    assert row.result_summary == "42"
    assert row.conversation_id == conversation_id


def test_failed_tool_call_is_reported_in_band_not_as_turn_error(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    events = run_turn(mock_client, conversation_id, "calc: 1 / 0")
    names = [name for name, _ in events]

    assert "error" not in names  # the failure is a tool_result, not a turn error
    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result["ok"] is False
    assert "division by zero" in tool_result["error"]

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assistant = messages[-1]
    assert assistant["status"] == "complete"
    assert "division by zero" in assistant["content"]


def test_iteration_cap_stops_a_model_that_never_stops_calling_tools(mock_client):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    events = run_turn(mock_client, conversation_id, "toolloop: go")
    names = [name for name, _ in events]

    assert names.count("tool_call") == MAX_TOOL_ITERATIONS
    assert names.count("tool_result") == MAX_TOOL_ITERATIONS
    assert "error" not in names

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assistant = messages[-1]
    assert assistant["status"] == "complete"  # degrades honestly, is not a failure
    assert "stopped calling tools" in assistant["content"]
    assert len(assistant["extra"]["tool_calls"]) == MAX_TOOL_ITERATIONS


def test_unavailable_tool_name_is_reported_without_crashing_the_turn(mock_client, monkeypatch):
    # Force the mock provider to request a tool that does not exist, and make
    # sure the loop reports that in-band rather than raising. `monkeypatch`
    # restores the original method automatically at teardown.
    from gaia.llm import mock_provider
    from gaia.llm.base import StreamEvent, ToolCallRequest, Usage

    async def scripted(
        self, messages, *, model, system=None, temperature=0.7, max_tokens=4096, tools=None
    ):
        messages = list(messages)
        if any(m.role == "tool" for m in messages):
            yield StreamEvent(type="text", text="acknowledged")
            yield StreamEvent(type="usage", usage=Usage(input_tokens=1, output_tokens=1))
            yield StreamEvent(type="done", stop_reason="end_turn")
            return
        yield StreamEvent(
            type="tool_use",
            tool_calls=[ToolCallRequest(id="call-x", name="not_a_real_tool", arguments={})],
        )
        yield StreamEvent(type="usage", usage=Usage(input_tokens=1, output_tokens=0))
        yield StreamEvent(type="done", stop_reason="tool_use")

    monkeypatch.setattr(mock_provider.MockProvider, "stream_chat", scripted)

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    events = run_turn(mock_client, conversation_id, "please use a tool")
    names = [name for name, _ in events]
    assert "error" not in names
    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result["ok"] is False
    assert "not available" in tool_result["error"]
