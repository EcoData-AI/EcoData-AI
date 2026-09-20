"""End-to-end CONFIRM path, over a live SSE connection.

`test_tool_confirmation.py` proves the wait/resolve store works in isolation.
This proves the whole path: a turn actually pauses mid-stream on a
`tool_confirm_required` event, a separate request resolves it, and the turn
resumes and completes correctly — approved and denied. python_sandbox is the
first CONFIRM-risk tool to exist, so until now this path had never run for
real.

The chat turn has to run on a background thread: `TestClient.stream()` blocks
until the generator finishes, and the generator itself is suspended
mid-stream awaiting the confirmation. Resolving it happens from the (still
free) main thread. FastAPI's TestClient keeps one persistent event loop for
its lifetime, so `tool_confirmation`'s `asyncio.Future` — created while
handling the streaming request — is resolved from the same loop that's
awaiting it, from the second request.
"""

from __future__ import annotations

import json
import threading
import time

from gaia.services import tool_confirmation


def _parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name: str | None = None
    for line in raw.splitlines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, json.loads(line[6:])))
            name = None
    return events


def _run_turn_in_background(
    client, conversation_id: str, content: str, out: dict
) -> threading.Thread:
    def target() -> None:
        with client.stream(
            "POST", "/api/chat", json={"conversation_id": conversation_id, "content": content}
        ) as response:
            out["status"] = response.status_code
            out["events"] = _parse_sse("".join(response.iter_text()))

    thread = threading.Thread(target=target)
    thread.start()
    return thread


def _wait_for_pending_call_id(timeout: float = 10.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tool_confirmation.pending_count() > 0:
            return next(iter(tool_confirmation._pending))  # noqa: SLF001 - test-only introspection
        time.sleep(0.01)
    raise TimeoutError("no pending confirmation appeared in time")


def test_confirm_approved_executes_the_tool_and_completes(mock_client, session):
    from sqlalchemy import select

    from gaia.db.models import ToolCall

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = _run_turn_in_background(mock_client, conversation_id, "pyexec: print(6 * 7)", out)

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": True})
    assert resolve.status_code == 204

    thread.join(timeout=30)
    assert not thread.is_alive(), "turn did not complete after approval"

    names = [name for name, _ in out["events"]]
    assert "tool_confirm_required" in names
    confirm = next(data for name, data in out["events"] if name == "tool_confirm_required")
    assert confirm["call_id"] == call_id
    assert confirm["tool"] == "python_sandbox"

    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is True
    assert result["content"].strip() == "42"
    assert "error" not in names

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assistant = messages[-1]
    assert assistant["status"] == "complete"
    assert "42" in assistant["content"]

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.tool_name == "python_sandbox"
    assert row.risk_level == "confirm"
    assert row.approval == "approved"
    assert row.status == "succeeded"


def test_confirm_denied_skips_execution_and_still_completes(mock_client, session):
    from sqlalchemy import select

    from gaia.db.models import ToolCall

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = _run_turn_in_background(
        mock_client, conversation_id, "pyexec: print('should never run')", out
    )

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": False})
    assert resolve.status_code == 204

    thread.join(timeout=30)
    assert not thread.is_alive(), "turn did not complete after denial"

    names = [name for name, _ in out["events"]]
    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is False
    assert "denied" in (result["error"] or "").lower()
    assert "error" not in names  # a denial is a tool_result, not a turn-level error

    messages = mock_client.get(f"/api/conversations/{conversation_id}/messages").json()
    assistant = messages[-1]
    assert assistant["status"] == "complete"

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.approval == "denied"
    assert row.status == "failed"


def test_resolving_an_unknown_confirmation_id_returns_404(client):
    response = client.post("/api/chat/tool-confirmations/no-such-id", json={"approved": True})
    assert response.status_code == 404


def test_filesystem_write_confirm_approved_writes_the_file(mock_client, session, tmp_path):
    from sqlalchemy import select

    from gaia.db.models import ToolCall
    from gaia.services import workspace_service

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)
    target = workspace / "out.txt"

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = _run_turn_in_background(
        mock_client, conversation_id, f"fswrite:{target}|hello from the model", out
    )

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": True})
    assert resolve.status_code == 204
    thread.join(timeout=30)
    assert not thread.is_alive()

    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is True
    assert target.exists()
    assert target.read_text() == "hello from the model"

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.tool_name == "filesystem_write"
    assert row.approval == "approved"
    assert row.status == "succeeded"


def test_filesystem_write_confirm_denied_never_touches_the_file(mock_client, session, tmp_path):
    from sqlalchemy import select

    from gaia.db.models import ToolCall
    from gaia.services import workspace_service

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)
    target = workspace / "out.txt"

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = _run_turn_in_background(
        mock_client, conversation_id, f"fswrite:{target}|should never be written", out
    )

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": False})
    assert resolve.status_code == 204
    thread.join(timeout=30)
    assert not thread.is_alive()

    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is False
    assert not target.exists()

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.tool_name == "filesystem_write"
    assert row.approval == "denied"
    assert row.status == "failed"


def test_terminal_confirm_approved_runs_the_command(mock_client, session, tmp_path):
    import sys

    from sqlalchemy import select

    from gaia.db.models import ToolCall
    from gaia.services import workspace_service

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    command = f'"{sys.executable}" -c "print(21 * 2)"'
    thread = _run_turn_in_background(
        mock_client, conversation_id, f"term:{workspace}|{command}", out
    )

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": True})
    assert resolve.status_code == 204
    thread.join(timeout=30)
    assert not thread.is_alive()

    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is True
    assert result["content"].strip() == "42"

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.tool_name == "terminal"
    assert row.risk_level == "confirm"
    assert row.approval == "approved"
    assert row.status == "succeeded"


def test_terminal_confirm_denied_never_runs_the_command(mock_client, session, tmp_path):
    from sqlalchemy import select

    from gaia.db.models import ToolCall
    from gaia.services import workspace_service

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workspace_service.add_root(session, path=str(workspace), writable=True)
    marker = workspace / "should-not-exist.txt"

    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = _run_turn_in_background(
        mock_client, conversation_id, f"term:{workspace}|echo hi > {marker.name}", out
    )

    call_id = _wait_for_pending_call_id()
    resolve = mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": False})
    assert resolve.status_code == 204
    thread.join(timeout=30)
    assert not thread.is_alive()

    result = next(data for name, data in out["events"] if name == "tool_result")
    assert result["ok"] is False
    assert not marker.exists()

    row = session.execute(select(ToolCall).where(ToolCall.id == call_id)).scalar_one()
    assert row.tool_name == "terminal"
    assert row.approval == "denied"
    assert row.status == "failed"
