"""Course outline validation, parsing, and generation (`gaia.study.curriculum`)."""

from __future__ import annotations

import pytest

from gaia.llm.base import ProviderConfig, StreamEvent
from gaia.llm.mock_provider import MOCK_COURSE_MODULES, MockProvider
from gaia.study.curriculum import (
    CurriculumError,
    all_topics,
    find_topic,
    generate_outline,
    parse_outline_json,
    validate_outline,
)

GOOD = {
    "modules": [
        {"title": "Foundations", "topics": ["Players and strategies", "Payoff matrices"]},
        {"title": "Equilibria", "topics": ["Dominant strategies", "Nash equilibrium"]},
    ]
}


def test_a_good_outline_validates_and_whitespace_is_normalised():
    messy = {"modules": [{"title": "  Foundations ", "topics": ["Players   and strategies"]}]}
    assert validate_outline(messy) == {
        "modules": [{"title": "Foundations", "topics": ["Players and strategies"]}]
    }
    assert validate_outline(GOOD) == GOOD


@pytest.mark.parametrize(
    "outline",
    [
        None,
        {},
        {"modules": []},
        {"modules": "not a list"},
        {"modules": [{"title": "", "topics": ["a"]}]},
        {"modules": [{"title": "M", "topics": []}]},
        {"modules": [{"title": "M", "topics": ["  "]}]},
        {"modules": [{"title": "M", "topics": [42]}]},
        {"modules": ["not an object"]},
        {"modules": [{"title": "M", "topics": ["x" * 201]}]},
    ],
)
def test_bad_outlines_are_rejected(outline):
    with pytest.raises(CurriculumError):
        validate_outline(outline)


def test_topic_titles_must_be_unique_across_the_course_ignoring_case():
    outline = {
        "modules": [
            {"title": "A", "topics": ["Nash equilibrium"]},
            {"title": "B", "topics": ["nash  EQUILIBRIUM"]},
        ]
    }
    with pytest.raises(CurriculumError, match="unique"):
        validate_outline(outline)


def test_all_topics_and_find_topic():
    assert all_topics(GOOD) == [
        "Players and strategies",
        "Payoff matrices",
        "Dominant strategies",
        "Nash equilibrium",
    ]
    assert find_topic(GOOD, "  nash EQUILIBRIUM ") == "Nash equilibrium"
    assert find_topic(GOOD, "Mixed strategies") is None
    assert all_topics(None) == []


def test_parse_tolerates_a_code_fence_and_preamble():
    assert parse_outline_json('{"modules": []}') == {"modules": []}
    assert parse_outline_json('Here you go:\n```json\n{"modules": []}\n```') == {"modules": []}
    assert parse_outline_json('Sure! {"modules": []} Hope that helps.') == {"modules": []}


@pytest.mark.parametrize("text", ["", "no json here", "{not json}"])
def test_parse_rejects_non_json(text):
    with pytest.raises(CurriculumError):
        parse_outline_json(text)


async def test_generate_outline_with_the_mock_provider():
    outline = await generate_outline(
        MockProvider(ProviderConfig()), "mock-echo", subject="Game theory"
    )
    assert outline == {"modules": MOCK_COURSE_MODULES}


async def test_generate_outline_rejects_an_unusable_reply():
    class Prose(MockProvider):
        async def stream_chat(self, messages, **kwargs):
            yield StreamEvent(type="text", text="Game theory is the study of strategic choice.")
            yield StreamEvent(type="done", stop_reason="end_turn")

    with pytest.raises(CurriculumError):
        await generate_outline(Prose(ProviderConfig()), "mock-echo", subject="Game theory")
