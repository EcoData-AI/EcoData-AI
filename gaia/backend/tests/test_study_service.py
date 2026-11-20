"""Courses, progress and tutoring sessions in the database (`study_service`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from gaia.db.models import Conversation, LearningProgress
from gaia.services import study_service
from gaia.services.study_service import StudyError

OUTLINE = {
    "modules": [
        {"title": "Foundations", "topics": ["Players and strategies", "Payoff matrices"]},
        {"title": "Equilibria", "topics": ["Nash equilibrium"]},
    ]
}


def _plan(session, **kwargs):
    return study_service.create_plan(
        session, subject=kwargs.pop("subject", "Game theory"), outline=OUTLINE, **kwargs
    )


def test_create_plan_stores_a_validated_outline_and_unassessed_level(session):
    plan = _plan(session, goal="  read economics papers  ")
    assert plan.outline == OUTLINE
    assert plan.goal == "read economics papers"
    assert plan.level is None
    assert plan.active is True


def test_create_plan_rejects_a_bad_outline_and_stores_nothing(session):
    with pytest.raises(StudyError, match="outline"):
        study_service.create_plan(session, subject="X", outline={"modules": []})
    assert study_service.list_plans(session) == []


def test_level_is_validated_and_normalised(session):
    assert _plan(session, level=" Beginner ").level == "beginner"
    with pytest.raises(StudyError, match="level"):
        _plan(session, level="expert")


def test_record_review_creates_then_updates_one_row_per_topic(session):
    plan = _plan(session)
    now = datetime(2026, 11, 20, tzinfo=UTC)

    first = study_service.record_review(
        session, plan, topic="nash equilibrium", score=4, note="mixed up best responses", now=now
    )
    assert first.topic == "Nash equilibrium"  # the outline's own spelling
    assert first.attempts == 1
    assert first.last_score == 4
    assert first.last_note == "mixed up best responses"

    second = study_service.record_review(session, plan, topic="Nash equilibrium", score=5, now=now)
    assert second.id == first.id
    assert second.attempts == 2
    assert second.last_note is None
    assert len(session.execute(select(LearningProgress)).scalars().all()) == 1


@pytest.mark.parametrize("score", [-1, 6, 2.5, True, "4"])
def test_record_review_rejects_bad_scores(session, score):
    plan = _plan(session)
    with pytest.raises(StudyError, match="score"):
        study_service.record_review(session, plan, topic="Nash equilibrium", score=score)


def test_record_review_rejects_a_topic_not_in_the_course_and_lists_the_real_ones(session):
    plan = _plan(session)
    with pytest.raises(StudyError) as excinfo:
        study_service.record_review(session, plan, topic="Mixed strategies", score=3)
    assert "Payoff matrices" in str(excinfo.value)


def test_plan_status_reports_progress_due_reviews_and_the_current_topic(session):
    plan = _plan(session)
    then = datetime(2026, 11, 1, tzinfo=UTC)
    for _ in range(5):
        study_service.record_review(
            session, plan, topic="Players and strategies", score=5, now=then
        )
    study_service.record_review(session, plan, topic="Payoff matrices", score=1, now=then)

    status = study_service.plan_status(plan, now=then + timedelta(hours=1))
    assert status.topic_count == 3
    assert status.mastered_count == 1
    assert status.due == []
    # Teaching order: the first not-yet-mastered topic.
    assert status.current is not None and status.current.topic == "Payoff matrices"

    # A day later the failed topic is due again; the mastered one is not.
    later = study_service.plan_status(plan, now=then + timedelta(days=2))
    assert [t.topic for t in later.due] == ["Payoff matrices"]


def test_current_is_none_once_everything_is_mastered(session):
    plan = _plan(session)
    for topic in ("Players and strategies", "Payoff matrices", "Nash equilibrium"):
        for _ in range(3):
            study_service.record_review(session, plan, topic=topic, score=5)
    assert study_service.plan_status(plan).current is None


def test_reset_progress_clears_rows_but_keeps_the_course(session):
    plan = _plan(session)
    study_service.record_review(session, plan, topic="Nash equilibrium", score=4)
    study_service.reset_progress(session, plan)
    assert plan.progress == []
    assert study_service.get_plan(session, plan.id) is not None


def test_start_session_links_a_new_conversation(session):
    plan = _plan(session)
    conversation = study_service.start_session(session, plan)
    assert conversation.study_plan_id == plan.id
    assert conversation.title == "Study: Game theory"
    assert study_service.latest_session_id(session, plan.id) == conversation.id


def test_deleting_a_course_deletes_progress_and_keeps_its_sessions(session):
    plan = _plan(session)
    study_service.record_review(session, plan, topic="Nash equilibrium", score=4)
    conversation = study_service.start_session(session, plan)

    assert study_service.delete_plan(session, plan.id) is True
    session.expire_all()

    assert session.execute(select(LearningProgress)).scalars().all() == []
    kept = session.get(Conversation, conversation.id)
    assert kept is not None and kept.study_plan_id is None
    assert study_service.delete_plan(session, plan.id) is False
