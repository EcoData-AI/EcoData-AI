"""Courses, per-topic progress, and what the tutor should work on next.

CRUD shape mirrors `project_service.py`. The pure parts — SM-2 and outline
validation — live in `gaia/study/`; this module is where they meet the
database.

Timestamps: SQLite hands `DateTime(timezone=True)` columns back naive, so every
comparison here goes through `_aware()`, which reads a naive value as UTC (the
only thing GAIA ever writes — see `db.base.utcnow`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaia.db.base import utcnow
from gaia.db.models import Conversation, LearningProgress, StudyPlan
from gaia.llm.registry import build_provider
from gaia.services import settings_service
from gaia.study import curriculum, scheduling
from gaia.study.curriculum import CurriculumError

DEFAULT_SESSION_TITLE_PREFIX = "Study: "


class StudyError(ValueError):
    """A request the study layer refuses. The message is user-readable."""


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _clean_level(level: str | None) -> str | None:
    if level is None:
        return None
    cleaned = level.strip().casefold()
    if cleaned not in curriculum.LEVELS:
        raise StudyError(f"level must be one of {', '.join(curriculum.LEVELS)}")
    return cleaned


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------


def create_plan(
    session: Session,
    *,
    subject: str,
    outline: Any,
    goal: str | None = None,
    level: str | None = None,
) -> StudyPlan:
    if not subject or not subject.strip():
        raise StudyError("a course needs a subject")
    try:
        cleaned_outline = curriculum.validate_outline(outline)
    except CurriculumError as exc:
        raise StudyError(f"That course outline can't be used: {exc}.") from exc
    plan = StudyPlan(
        subject=" ".join(subject.split())[:200],
        goal=goal.strip() if goal and goal.strip() else None,
        level=_clean_level(level),
        outline=cleaned_outline,
        active=True,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def get_plan(session: Session, plan_id: str) -> StudyPlan | None:
    return session.get(StudyPlan, plan_id)


def list_plans(session: Session, *, include_inactive: bool = False) -> list[StudyPlan]:
    stmt = select(StudyPlan)
    if not include_inactive:
        stmt = stmt.where(StudyPlan.active.is_(True))
    stmt = stmt.order_by(StudyPlan.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def update_plan(
    session: Session,
    plan: StudyPlan,
    *,
    goal: str | None = None,
    level: str | None = None,
    active: bool | None = None,
) -> StudyPlan:
    if goal is not None:
        plan.goal = goal.strip() or None
    if level is not None:
        plan.level = _clean_level(level)
    if active is not None:
        plan.active = active
    session.commit()
    session.refresh(plan)
    return plan


def delete_plan(session: Session, plan_id: str) -> bool:
    plan = session.get(StudyPlan, plan_id)
    if plan is None:
        return False
    session.delete(plan)
    session.commit()
    return True


def reset_progress(session: Session, plan: StudyPlan) -> None:
    for row in list(plan.progress):
        session.delete(row)
    session.commit()
    session.refresh(plan)


# --------------------------------------------------------------------------
# Progress
# --------------------------------------------------------------------------


def record_review(
    session: Session,
    plan: StudyPlan,
    *,
    topic: str,
    score: int,
    note: str | None = None,
    now: datetime | None = None,
) -> LearningProgress:
    """Grade one attempt at `topic` (0–5) and reschedule it."""
    if isinstance(score, bool) or not isinstance(score, int):
        raise StudyError("score must be a whole number from 0 to 5")
    if not scheduling.MIN_SCORE <= score <= scheduling.MAX_SCORE:
        raise StudyError("score must be a whole number from 0 to 5")
    canonical = curriculum.find_topic(plan.outline, topic)
    if canonical is None:
        raise StudyError(
            f"'{topic}' is not a topic in this course. Topics are: "
            + "; ".join(curriculum.all_topics(plan.outline))
        )

    now = now or utcnow()
    row = session.execute(
        select(LearningProgress).where(
            LearningProgress.study_plan_id == plan.id, LearningProgress.topic == canonical
        )
    ).scalar_one_or_none()
    if row is None:
        row = LearningProgress(study_plan_id=plan.id, topic=canonical)
        session.add(row)
        state = scheduling.ReviewState()
    else:
        state = scheduling.ReviewState(
            ease=row.ease,
            interval_days=row.interval_days,
            repetitions=row.repetitions,
            mastery=row.mastery,
            attempts=row.attempts,
        )

    outcome = scheduling.review(state, score, now)
    row.ease = outcome.state.ease
    row.interval_days = outcome.state.interval_days
    row.repetitions = outcome.state.repetitions
    row.mastery = outcome.state.mastery
    row.attempts = outcome.state.attempts
    row.last_score = score
    row.last_note = note.strip()[:500] if note and note.strip() else None
    row.last_reviewed_at = now
    row.next_review_at = outcome.next_review_at
    session.commit()
    session.refresh(row)
    return row


@dataclass(slots=True)
class TopicStatus:
    module: str
    topic: str
    mastery: float = 0.0
    attempts: int = 0
    last_score: int | None = None
    last_note: str | None = None
    last_reviewed_at: datetime | None = None
    next_review_at: datetime | None = None
    due: bool = False

    @property
    def mastered(self) -> bool:
        return self.mastery >= scheduling.MASTERED_THRESHOLD

    @property
    def started(self) -> bool:
        return self.attempts > 0


@dataclass(slots=True)
class PlanStatus:
    topics: list[TopicStatus] = field(default_factory=list)

    @property
    def topic_count(self) -> int:
        return len(self.topics)

    @property
    def mastered_count(self) -> int:
        return sum(1 for t in self.topics if t.mastered)

    @property
    def due(self) -> list[TopicStatus]:
        return sorted(
            (t for t in self.topics if t.due), key=lambda t: t.next_review_at or datetime.min
        )

    @property
    def current(self) -> TopicStatus | None:
        """The first topic, in teaching order, not yet mastered."""
        return next((t for t in self.topics if not t.mastered), None)


def plan_status(plan: StudyPlan, now: datetime | None = None) -> PlanStatus:
    now = now or utcnow()
    rows = {curriculum.normalise_topic(r.topic): r for r in plan.progress}
    status = PlanStatus()
    for module in (plan.outline or {}).get("modules", []):
        for topic in module.get("topics", []):
            row = rows.get(curriculum.normalise_topic(topic))
            item = TopicStatus(module=module["title"], topic=topic)
            if row is not None:
                next_review = _aware(row.next_review_at)
                item.mastery = row.mastery
                item.attempts = row.attempts
                item.last_score = row.last_score
                item.last_note = row.last_note
                item.last_reviewed_at = _aware(row.last_reviewed_at)
                item.next_review_at = next_review
                item.due = scheduling.is_due(next_review, now)
            status.topics.append(item)
    return status


# --------------------------------------------------------------------------
# Tutoring sessions
# --------------------------------------------------------------------------


def start_session(session: Session, plan: StudyPlan) -> Conversation:
    conversation = Conversation(
        title=f"{DEFAULT_SESSION_TITLE_PREFIX}{plan.subject}"[:300], study_plan_id=plan.id
    )
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


def attach_conversation(session: Session, conversation_id: str, plan: StudyPlan) -> bool:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        return False
    conversation.study_plan_id = plan.id
    session.commit()
    return True


def latest_session_id(session: Session, plan_id: str) -> str | None:
    return session.execute(
        select(Conversation.id)
        .where(Conversation.study_plan_id == plan_id, Conversation.archived.is_(False))
        .order_by(Conversation.last_message_at.desc().nulls_last(), Conversation.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


async def generate_plan(
    session: Session, *, subject: str, goal: str | None = None, level: str | None = None
) -> StudyPlan:
    """Create a course whose outline the configured model writes.

    Raises `ProviderError` if the model cannot be reached, `StudyError` if it
    answered with something that is not a usable outline (or `level` is bad).
    Nothing is stored unless the outline validates.
    """
    level = _clean_level(level)
    provider = build_provider(session, settings_service.get_active_provider_id(session))
    model_id = await provider.resolve_model(
        settings_service.get(session, settings_service.ACTIVE_MODEL)
    )
    try:
        outline = await curriculum.generate_outline(
            provider, model_id, subject=subject, goal=goal, level=level
        )
    except CurriculumError as exc:
        raise StudyError(
            f"The model's course outline couldn't be used ({exc}). Try again, or switch to a "
            "more capable model in Settings."
        ) from exc
    return create_plan(session, subject=subject, goal=goal, level=level, outline=outline)
