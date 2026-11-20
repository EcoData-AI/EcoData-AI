"""Spaced repetition: SM-2, plus a mastery estimate the Study screen can show.

SM-2 (Wozniak, 1990) is deliberately the plain textbook version: each review
is graded 0–5; a grade below 3 resets the repetition count and brings the topic
back tomorrow, a passing grade grows the interval (1 day, then 6, then
`interval × ease`), and the ease factor drifts with how hard the recall was,
never below 1.3. Nothing here is tuned — it is the published algorithm.

Mastery is separate from scheduling on purpose. SM-2 answers "when should this
come back?", not "how well do you know it?", so mastery is an exponential
moving average of normalised grades: recent answers dominate, one lucky or
unlucky answer does not swing it to an extreme.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MIN_SCORE = 0
MAX_SCORE = 5
#: SM-2's own threshold: a grade at or above this counts as a successful recall.
PASSING_SCORE = 3
MIN_EASE = 1.3
DEFAULT_EASE = 2.5
#: Weight of the newest grade in the mastery moving average.
MASTERY_WEIGHT = 0.4
#: Mastery at or above this counts as "mastered" for progress and for the
#: tutor's choice of what to teach next.
MASTERED_THRESHOLD = 0.8


@dataclass(frozen=True, slots=True)
class ReviewState:
    ease: float = DEFAULT_EASE
    interval_days: float = 0.0
    repetitions: int = 0
    mastery: float = 0.0
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    state: ReviewState
    next_review_at: datetime


def review(state: ReviewState, score: int, now: datetime) -> ReviewOutcome:
    """Apply one graded review. `score` must already be in 0–5."""
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"score must be between {MIN_SCORE} and {MAX_SCORE}")

    if score < PASSING_SCORE:
        repetitions = 0
        interval = 1.0
    else:
        repetitions = state.repetitions + 1
        if repetitions == 1:
            interval = 1.0
        elif repetitions == 2:
            interval = 6.0
        else:
            interval = round(state.interval_days * state.ease, 2)

    miss = MAX_SCORE - score
    ease = max(MIN_EASE, state.ease + 0.1 - miss * (0.08 + miss * 0.02))

    normalised = score / MAX_SCORE
    mastery = (
        normalised
        if state.attempts == 0
        else (1 - MASTERY_WEIGHT) * state.mastery + MASTERY_WEIGHT * normalised
    )

    return ReviewOutcome(
        state=ReviewState(
            ease=round(ease, 4),
            interval_days=interval,
            repetitions=repetitions,
            mastery=round(mastery, 4),
            attempts=state.attempts + 1,
        ),
        next_review_at=now + timedelta(days=interval),
    )


def is_due(next_review_at: datetime | None, now: datetime) -> bool:
    return next_review_at is not None and next_review_at <= now
