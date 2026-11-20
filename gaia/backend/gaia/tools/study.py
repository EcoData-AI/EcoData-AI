"""Study tools — how the tutor turns a conversation into a course and keeps score.

* `start_course` (CONFIRM) — the model proposes an outline; the user sees the
  whole thing in the approval dialog before a course exists. On approval this
  conversation becomes the course's tutoring session.
* `record_study_progress` (SAFE) — grades one attempt at a topic and
  reschedules it (SM-2).
* `set_study_level` (SAFE) — stores the result of the diagnostic.

Why the last two are SAFE when `remember` is CONFIRM: they write nowhere but
the course the user explicitly created and is studying in this very
conversation, everything they write is shown and resettable on the Study
screen, and every call is still in the `tool_calls` audit trail. Grading is
also the core loop of tutoring — an approval dialog after every answer would
make the feature unusable. Neither can create a course, touch another course,
or write memory.

All three need to know which conversation they run in, so they implement
`execute_with_context`; called without one (`execute`), they refuse.
"""

from __future__ import annotations

from typing import Any

from gaia.db.models import Conversation
from gaia.db.session import session_scope
from gaia.services import study_service
from gaia.services.study_service import StudyError
from gaia.study import curriculum
from gaia.study.scheduling import MAX_SCORE, MIN_SCORE
from gaia.tools.base import RiskLevel, Tool, ToolContext, ToolResult

_NO_CONTEXT = "This tool only works inside a conversation."
_NOT_A_SESSION = (
    "This conversation is not a study session for any course. Use start_course first, or "
    "the user can open a course from the Study screen."
)


def _failure(message: str) -> ToolResult:
    return ToolResult(ok=False, content="", error=message)


class StartCourseTool(Tool):
    name = "start_course"
    description = (
        "Create a structured course when the user asks to be taught a subject (e.g. 'teach "
        "me game theory'), and make this conversation its tutoring session. Propose the "
        "outline yourself: 3-8 modules in teaching order, each with 2-6 topics small enough "
        "to teach and check in one sitting, topic titles unique. Leave 'level' out unless "
        "the user stated it — you will assess it with a short diagnostic. The user approves "
        "the outline before the course is created."
    )
    parameters = {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "What the course teaches."},
            "goal": {
                "type": "string",
                "description": "What the user wants to be able to do, in their own terms.",
            },
            "level": {"type": "string", "enum": list(curriculum.LEVELS)},
            "modules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "topics"],
                },
            },
        },
        "required": ["subject", "modules"],
    }
    risk_level = RiskLevel.CONFIRM

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return _failure(_NO_CONTEXT)

    async def execute_with_context(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        if context.conversation_id is None:
            return _failure(_NO_CONTEXT)
        try:
            with session_scope() as session:
                plan = study_service.create_plan(
                    session,
                    subject=str(arguments.get("subject") or ""),
                    goal=arguments.get("goal") if isinstance(arguments.get("goal"), str) else None,
                    level=arguments.get("level") or None,
                    outline={"modules": arguments.get("modules")},
                )
                study_service.attach_conversation(session, context.conversation_id, plan)
                topics = curriculum.all_topics(plan.outline)
                summary = {
                    "plan_id": plan.id,
                    "subject": plan.subject,
                    "level": plan.level,
                    "modules": len(plan.outline["modules"]),
                    "topics": len(topics),
                    "first_topic": topics[0],
                }
        except StudyError as exc:
            return _failure(str(exc))
        except Exception as exc:  # backstop — must never raise past here
            return _failure(f"unexpected error: {exc}")

        level_line = (
            f"Level: {summary['level']}."
            if summary["level"]
            else "Level: not assessed yet — begin with two or three short diagnostic questions, "
            "then call set_study_level."
        )
        return ToolResult(
            ok=True,
            content=(
                f"Created the course '{summary['subject']}' ({summary['modules']} modules, "
                f"{summary['topics']} topics). This conversation is now its tutoring session. "
                f"{level_line} First topic: {summary['first_topic']}."
            ),
            display=summary,
        )


class RecordStudyProgressTool(Tool):
    name = "record_study_progress"
    description = (
        "In a study session, record how well the user just did on one course topic, after "
        "they have actually answered a question or exercise on it — never before, and never "
        "for something you only explained. Score 0-5: 5 correct and fluent, 4 correct with "
        "hesitation, 3 correct with real difficulty, 2 wrong but close, 1 wrong, 0 no idea. "
        "This schedules the topic's next review."
    )
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The topic title, as in the course."},
            "score": {"type": "integer", "minimum": MIN_SCORE, "maximum": MAX_SCORE},
            "note": {
                "type": "string",
                "description": "One line on what went right or wrong — e.g. a misconception.",
            },
        },
        "required": ["topic", "score"],
    }
    risk_level = RiskLevel.SAFE

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return _failure(_NO_CONTEXT)

    async def execute_with_context(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        if context.conversation_id is None:
            return _failure(_NO_CONTEXT)
        topic = arguments.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            return _failure("'topic' must be a non-empty string")
        try:
            with session_scope() as session:
                conversation = session.get(Conversation, context.conversation_id)
                plan = (
                    study_service.get_plan(session, conversation.study_plan_id)
                    if conversation is not None and conversation.study_plan_id
                    else None
                )
                if plan is None:
                    return _failure(_NOT_A_SESSION)
                row = study_service.record_review(
                    session,
                    plan,
                    topic=topic,
                    score=arguments.get("score"),  # type: ignore[arg-type] - validated there
                    note=arguments.get("note") if isinstance(arguments.get("note"), str) else None,
                )
                display = {
                    "topic": row.topic,
                    "score": row.last_score,
                    "mastery": row.mastery,
                    "attempts": row.attempts,
                    "interval_days": row.interval_days,
                    "next_review_at": (
                        row.next_review_at.isoformat() if row.next_review_at else None
                    ),
                }
        except StudyError as exc:
            return _failure(str(exc))
        except Exception as exc:  # backstop — must never raise past here
            return _failure(f"unexpected error: {exc}")

        days = display["interval_days"]
        when = "tomorrow" if days <= 1 else f"in {days:g} days"
        return ToolResult(
            ok=True,
            content=(
                f"Recorded {display['score']}/5 on '{display['topic']}'. Mastery is now "
                f"{round(display['mastery'] * 100)}% after {display['attempts']} attempt(s); "
                f"next review {when}."
            ),
            display=display,
        )


class SetStudyLevelTool(Tool):
    name = "set_study_level"
    description = (
        "In a study session, store the user's level once your short diagnostic has shown it. "
        "Call it again later only if their answers show the level was clearly wrong."
    )
    parameters = {
        "type": "object",
        "properties": {
            "level": {"type": "string", "enum": list(curriculum.LEVELS)},
            "rationale": {
                "type": "string",
                "description": "One line on what in their answers showed this level.",
            },
        },
        "required": ["level"],
    }
    risk_level = RiskLevel.SAFE

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return _failure(_NO_CONTEXT)

    async def execute_with_context(
        self, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        if context.conversation_id is None:
            return _failure(_NO_CONTEXT)
        level = arguments.get("level")
        if not isinstance(level, str):
            return _failure(f"'level' must be one of {', '.join(curriculum.LEVELS)}")
        try:
            with session_scope() as session:
                conversation = session.get(Conversation, context.conversation_id)
                plan = (
                    study_service.get_plan(session, conversation.study_plan_id)
                    if conversation is not None and conversation.study_plan_id
                    else None
                )
                if plan is None:
                    return _failure(_NOT_A_SESSION)
                study_service.update_plan(session, plan, level=level)
                stored, subject = plan.level, plan.subject
        except StudyError as exc:
            return _failure(str(exc))
        except Exception as exc:  # backstop — must never raise past here
            return _failure(f"unexpected error: {exc}")

        return ToolResult(
            ok=True,
            content=f"Level for '{subject}' set to {stored}.",
            display={"subject": subject, "level": stored},
        )
