"""The tutor end to end: study tools, tutor-mode context, and the chat path that
turns "teach me X" into a course that adapts to graded answers."""

from __future__ import annotations

import json
import threading
import time

from sqlalchemy import select

from gaia.core.context_builder import build_context
from gaia.db.models import LearningProgress, Message, ToolCall
from gaia.services import study_service, tool_confirmation
from gaia.tools.base import RiskLevel, ToolContext
from gaia.tools.study import RecordStudyProgressTool, SetStudyLevelTool, StartCourseTool

OUTLINE = {
    "modules": [
        {"title": "Foundations", "topics": ["Players and strategies", "Payoff matrices"]},
        {"title": "Equilibria", "topics": ["Nash equilibrium"]},
    ]
}


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


def _turn(client, conversation_id: str, content: str) -> list[tuple[str, dict]]:
    with client.stream(
        "POST", "/api/chat", json={"conversation_id": conversation_id, "content": content}
    ) as response:
        assert response.status_code == 200
        return _parse_sse("".join(response.iter_text()))


def _event(events, name):
    return next(data for event, data in events if event == name)


# --------------------------------------------------------------------------
# Tools, called directly
# --------------------------------------------------------------------------


def test_risk_levels():
    assert StartCourseTool.risk_level is RiskLevel.CONFIRM
    assert RecordStudyProgressTool.risk_level is RiskLevel.SAFE
    assert SetStudyLevelTool.risk_level is RiskLevel.SAFE


async def test_every_study_tool_refuses_without_a_conversation():
    for tool in (StartCourseTool(), RecordStudyProgressTool(), SetStudyLevelTool()):
        assert (await tool.execute({})).ok is False
        assert (await tool.execute_with_context({}, ToolContext())).ok is False


async def test_start_course_creates_a_plan_and_links_the_conversation(session):
    conversation = study_service.start_session(
        session, study_service.create_plan(session, subject="Old", outline=OUTLINE)
    )
    result = await StartCourseTool().execute_with_context(
        {"subject": "Game theory", "goal": "read papers", **OUTLINE},
        ToolContext(conversation_id=conversation.id),
    )
    assert result.ok is True, result.error
    assert "not assessed" in result.content
    session.expire_all()
    plan = study_service.get_plan(session, result.display["plan_id"])
    assert plan.subject == "Game theory"
    assert session.get(type(conversation), conversation.id).study_plan_id == plan.id


async def test_start_course_with_a_bad_outline_explains_what_to_fix(session):
    conversation = study_service.start_session(
        session, study_service.create_plan(session, subject="Old", outline=OUTLINE)
    )
    result = await StartCourseTool().execute_with_context(
        {"subject": "Game theory", "modules": [{"title": "A", "topics": []}]},
        ToolContext(conversation_id=conversation.id),
    )
    assert result.ok is False
    assert "topics" in result.error


async def test_progress_and_level_tools_need_a_study_session(session):
    from gaia.services import conversation_service

    plain = conversation_service.create_conversation(session)
    context = ToolContext(conversation_id=plain.id)
    graded = await RecordStudyProgressTool().execute_with_context(
        {"topic": "Nash equilibrium", "score": 4}, context
    )
    assert graded.ok is False and "not a study session" in graded.error
    level = await SetStudyLevelTool().execute_with_context({"level": "beginner"}, context)
    assert level.ok is False and "not a study session" in level.error


async def test_record_progress_and_set_level_in_a_session(session):
    plan = study_service.create_plan(session, subject="Game theory", outline=OUTLINE)
    context = ToolContext(conversation_id=study_service.start_session(session, plan).id)

    graded = await RecordStudyProgressTool().execute_with_context(
        {"topic": "payoff matrices", "score": 2, "note": "transposed the matrix"}, context
    )
    assert graded.ok is True, graded.error
    assert "2/5" in graded.content and "tomorrow" in graded.content

    unknown = await RecordStudyProgressTool().execute_with_context(
        {"topic": "Auctions", "score": 3}, context
    )
    assert unknown.ok is False and "Payoff matrices" in unknown.error

    level = await SetStudyLevelTool().execute_with_context({"level": "intermediate"}, context)
    assert level.ok is True
    bad = await SetStudyLevelTool().execute_with_context({"level": "wizard"}, context)
    assert bad.ok is False

    session.expire_all()
    plan = study_service.get_plan(session, plan.id)
    assert plan.level == "intermediate"
    assert plan.progress[0].last_note == "transposed the matrix"


# --------------------------------------------------------------------------
# Tutor-mode context
# --------------------------------------------------------------------------


def _user(content: str) -> Message:
    return Message(role="user", content=content, sequence=1, status="complete")


def test_tutor_section_asks_for_a_diagnostic_when_the_level_is_unknown(session):
    plan = study_service.create_plan(session, subject="Game theory", goal="papers", outline=OUTLINE)
    built = build_context(
        history=[_user("hi")],
        context_window=32_000,
        study_plan=plan,
        study_status=study_service.plan_status(plan),
    )
    assert "tutor" in built.sources
    assert "## Tutor mode — course: Game theory" in built.system
    assert "Their goal: papers" in built.system
    assert "diagnostic" in built.system
    assert "Focus topic: Players and strategies" in built.system
    assert "do not give the answer" in built.system
    assert "- Nash equilibrium — not started" in built.system


def test_tutor_section_reflects_progress_and_due_reviews(session):
    from datetime import timedelta

    from gaia.db.base import utcnow

    plan = study_service.create_plan(
        session, subject="Game theory", level="beginner", outline=OUTLINE
    )
    long_ago = utcnow() - timedelta(days=10)
    for _ in range(4):
        study_service.record_review(session, plan, topic="Players and strategies", score=5)
    study_service.record_review(
        session, plan, topic="Payoff matrices", score=1, note="mixed rows", now=long_ago
    )

    built = build_context(
        history=[_user("hi")],
        context_window=32_000,
        study_plan=plan,
        study_status=study_service.plan_status(plan),
    )
    assert "Level: beginner" in built.system
    assert "diagnostic" not in built.system
    assert "Progress: 1 of 3 topics mastered." in built.system
    assert "- Players and strategies — mastered, 100%" in built.system
    assert "due for spaced-repetition review: Payoff matrices" in built.system
    assert "last note: mixed rows" in built.system
    assert "Focus topic: Payoff matrices" in built.system


def test_no_tutor_section_outside_a_study_session():
    built = build_context(history=[_user("hi")], context_window=32_000)
    assert "tutor" not in built.sources
    assert "## Tutor mode" not in built.system


# --------------------------------------------------------------------------
# The whole loop, over /api/chat
# --------------------------------------------------------------------------


def _wait_for_pending_call_id(timeout: float = 10.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tool_confirmation.pending_count() > 0:
            return next(iter(tool_confirmation._pending))  # noqa: SLF001 - test-only introspection
        time.sleep(0.01)
    raise TimeoutError("no pending confirmation appeared in time")


def test_teach_me_creates_a_course_that_adapts_to_graded_answers(mock_client, session):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]

    # 1. "Teach me game theory" -> the model proposes a course; the user approves it.
    out: dict = {}

    def run() -> None:
        out["events"] = _turn(mock_client, conversation_id, "course: Game theory")

    thread = threading.Thread(target=run)
    thread.start()
    call_id = _wait_for_pending_call_id()
    assert (
        mock_client.post(
            f"/api/chat/tool-confirmations/{call_id}", json={"approved": True}
        ).status_code
        == 204
    )
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert _event(out["events"], "tool_result")["ok"] is True

    conversation = mock_client.get(f"/api/conversations/{conversation_id}").json()
    plan_id = conversation["study_plan_id"]
    assert plan_id is not None

    # 2. The next turn runs in tutor mode, starting with a diagnostic.
    events = _turn(mock_client, conversation_id, "ready")
    assert "tutor" in _event(events, "start")["context"]["sources"]

    # 3. The tutor sets the level and grades answers — no approval needed.
    level = _event(_turn(mock_client, conversation_id, "level: beginner"), "tool_result")
    assert level["ok"] is True
    weak = _event(_turn(mock_client, conversation_id, "grade: [mock] First idea|1"), "tool_result")
    assert weak["ok"] is True

    # 4. The course adapted: the weak topic is the focus and is scheduled back soon.
    plan = mock_client.get(f"/api/study/plans/{plan_id}").json()
    assert plan["level"] == "beginner"
    assert plan["current_topic"] == "[mock] First idea"
    first = plan["topics"][0]
    assert first["attempts"] == 1 and first["mastery"] == 0.2

    for _ in range(4):
        _turn(mock_client, conversation_id, "grade: [mock] First idea|5")
    plan = mock_client.get(f"/api/study/plans/{plan_id}").json()
    assert plan["mastered_count"] == 1
    assert plan["current_topic"] == "[mock] Second idea"

    # Every call is in the audit trail, with how it cleared the gate.
    rows = session.execute(select(ToolCall).order_by(ToolCall.created_at)).scalars().all()
    assert [(r.tool_name, r.approval) for r in rows[:3]] == [
        ("start_course", "approved"),
        ("set_study_level", "auto"),
        ("record_study_progress", "auto"),
    ]
    assert len(session.execute(select(LearningProgress)).scalars().all()) == 1


def test_denying_the_course_creates_nothing(mock_client, session):
    conversation_id = mock_client.post("/api/conversations", json={}).json()["id"]
    out: dict = {}
    thread = threading.Thread(
        target=lambda: out.setdefault(
            "events", _turn(mock_client, conversation_id, "course: Game theory")
        )
    )
    thread.start()
    call_id = _wait_for_pending_call_id()
    mock_client.post(f"/api/chat/tool-confirmations/{call_id}", json={"approved": False})
    thread.join(timeout=30)

    assert _event(out["events"], "tool_result")["ok"] is False
    assert mock_client.get("/api/study/plans").json() == []
    conversation = mock_client.get(f"/api/conversations/{conversation_id}").json()
    assert conversation["study_plan_id"] is None
