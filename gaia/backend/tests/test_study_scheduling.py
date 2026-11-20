"""SM-2 scheduling and the mastery estimate (`gaia.study.scheduling`). Pure — no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gaia.study.scheduling import (
    MASTERED_THRESHOLD,
    MIN_EASE,
    ReviewState,
    is_due,
    review,
)

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def test_first_pass_comes_back_tomorrow_then_in_six_days_then_grows_by_ease():
    first = review(ReviewState(), 5, NOW)
    assert first.state.repetitions == 1
    assert first.state.interval_days == 1.0
    assert first.next_review_at == NOW + timedelta(days=1)

    second = review(first.state, 5, NOW)
    assert second.state.interval_days == 6.0

    third = review(second.state, 5, NOW)
    assert third.state.interval_days == pytest.approx(6.0 * second.state.ease, abs=0.01)
    assert third.state.repetitions == 3


def test_a_failed_recall_resets_repetitions_and_returns_tomorrow():
    state = review(review(ReviewState(), 5, NOW).state, 5, NOW).state
    assert state.repetitions == 2

    failed = review(state, 1, NOW)
    assert failed.state.repetitions == 0
    assert failed.state.interval_days == 1.0
    assert failed.next_review_at == NOW + timedelta(days=1)


def test_ease_rises_on_perfect_recall_falls_on_hard_recall_and_has_a_floor():
    assert review(ReviewState(), 5, NOW).state.ease > ReviewState().ease
    assert review(ReviewState(), 3, NOW).state.ease < ReviewState().ease

    state = ReviewState()
    for _ in range(20):
        state = review(state, 0, NOW).state
    assert state.ease == MIN_EASE


def test_mastery_is_a_moving_average_not_the_last_grade():
    first = review(ReviewState(), 5, NOW).state
    assert first.mastery == 1.0  # the first answer is all there is to go on

    after_a_miss = review(first, 0, NOW).state
    # One bad answer pulls mastery down without wiping it out.
    assert 0.0 < after_a_miss.mastery < 1.0
    assert after_a_miss.attempts == 2


def test_consistent_good_answers_reach_mastered():
    state = review(ReviewState(), 2, NOW).state
    assert state.mastery < MASTERED_THRESHOLD
    for _ in range(5):
        state = review(state, 5, NOW).state
    assert state.mastery >= MASTERED_THRESHOLD


@pytest.mark.parametrize("score", [-1, 6])
def test_out_of_range_scores_are_rejected(score):
    with pytest.raises(ValueError):
        review(ReviewState(), score, NOW)


def test_is_due():
    assert is_due(NOW - timedelta(seconds=1), NOW)
    assert is_due(NOW, NOW)
    assert not is_due(NOW + timedelta(seconds=1), NOW)
    assert not is_due(None, NOW)
