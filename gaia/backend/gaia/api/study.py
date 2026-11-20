"""Study — courses, their progress, and opening tutoring sessions.

HTTP shape only; mirrors `api/projects.py`. The tutoring itself happens in an
ordinary chat conversation whose `study_plan_id` is set — `POST
/api/study/plans/{id}/sessions` creates one, and from then on it goes through
`/api/chat` like any other turn (see `core/context_builder.py`, "Tutor mode").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from gaia.db.models import StudyPlan
from gaia.db.session import get_session
from gaia.llm.base import ProviderError
from gaia.schemas.api import (
    ConversationOut,
    StudyPlanCreate,
    StudyPlanDetail,
    StudyPlanOut,
    StudyPlanUpdate,
    StudyReviewCreate,
    StudyTopicOut,
)
from gaia.services import study_service
from gaia.services.study_service import StudyError

router = APIRouter(prefix="/api/study", tags=["study"])


def _get_plan_or_404(session: Session, plan_id: str) -> StudyPlan:
    plan = study_service.get_plan(session, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No such course.")
    return plan


def _summary_fields(session: Session, plan: StudyPlan) -> dict:
    plan_status = study_service.plan_status(plan)
    return {
        "id": plan.id,
        "subject": plan.subject,
        "goal": plan.goal,
        "level": plan.level,
        "active": plan.active,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "topic_count": plan_status.topic_count,
        "mastered_count": plan_status.mastered_count,
        "due_count": len(plan_status.due),
        "current_topic": plan_status.current.topic if plan_status.current else None,
        "latest_conversation_id": study_service.latest_session_id(session, plan.id),
    }


def _detail(session: Session, plan: StudyPlan) -> StudyPlanDetail:
    topics = [
        StudyTopicOut(
            module=t.module,
            topic=t.topic,
            mastery=t.mastery,
            attempts=t.attempts,
            mastered=t.mastered,
            due=t.due,
            last_score=t.last_score,
            last_note=t.last_note,
            last_reviewed_at=t.last_reviewed_at,
            next_review_at=t.next_review_at,
        )
        for t in study_service.plan_status(plan).topics
    ]
    return StudyPlanDetail(
        **_summary_fields(session, plan), outline=plan.outline or {"modules": []}, topics=topics
    )


@router.get("/plans", response_model=list[StudyPlanOut])
def list_plans(
    include_inactive: bool = False, session: Session = Depends(get_session)
) -> list[StudyPlanOut]:
    plans = study_service.list_plans(session, include_inactive=include_inactive)
    return [StudyPlanOut(**_summary_fields(session, p)) for p in plans]


@router.post("/plans", response_model=StudyPlanDetail, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: StudyPlanCreate, session: Session = Depends(get_session)
) -> StudyPlanDetail:
    """With an `outline`, store it as given (after validation). Without one,
    the configured model writes it — the request waits for that."""
    try:
        if payload.outline is not None:
            plan = study_service.create_plan(
                session,
                subject=payload.subject,
                goal=payload.goal,
                level=payload.level,
                outline=payload.outline.model_dump(),
            )
        else:
            plan = await study_service.generate_plan(
                session, subject=payload.subject, goal=payload.goal, level=payload.level
            )
    except StudyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        detail = exc.message + (f" {exc.remedy}" if exc.remedy else "")
        raise HTTPException(status_code=502, detail=detail) from exc
    return _detail(session, plan)


@router.get("/plans/{plan_id}", response_model=StudyPlanDetail)
def get_plan(plan_id: str, session: Session = Depends(get_session)) -> StudyPlanDetail:
    return _detail(session, _get_plan_or_404(session, plan_id))


@router.patch("/plans/{plan_id}", response_model=StudyPlanDetail)
def update_plan(
    plan_id: str, payload: StudyPlanUpdate, session: Session = Depends(get_session)
) -> StudyPlanDetail:
    plan = _get_plan_or_404(session, plan_id)
    try:
        study_service.update_plan(session, plan, **payload.model_dump(exclude_unset=True))
    except StudyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail(session, plan)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: str, session: Session = Depends(get_session)) -> None:
    """Deletes the course and its progress; its study sessions stay, as
    ordinary conversations."""
    if not study_service.delete_plan(session, plan_id):
        raise HTTPException(status_code=404, detail="No such course.")


@router.post("/plans/{plan_id}/reviews", response_model=StudyPlanDetail)
def record_review(
    plan_id: str, payload: StudyReviewCreate, session: Session = Depends(get_session)
) -> StudyPlanDetail:
    """A self-graded review from the Study screen — the same SM-2 path the
    tutor's `record_study_progress` tool uses."""
    plan = _get_plan_or_404(session, plan_id)
    try:
        study_service.record_review(
            session, plan, topic=payload.topic, score=payload.score, note=payload.note
        )
    except StudyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _detail(session, plan)


@router.post("/plans/{plan_id}/reset", response_model=StudyPlanDetail)
def reset_progress(plan_id: str, session: Session = Depends(get_session)) -> StudyPlanDetail:
    plan = _get_plan_or_404(session, plan_id)
    study_service.reset_progress(session, plan)
    return _detail(session, plan)


@router.post(
    "/plans/{plan_id}/sessions",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def start_session(plan_id: str, session: Session = Depends(get_session)) -> ConversationOut:
    plan = _get_plan_or_404(session, plan_id)
    return ConversationOut.model_validate(study_service.start_session(session, plan))
