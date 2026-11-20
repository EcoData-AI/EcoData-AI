"""`/api/study` — HTTP shape, generation through the configured model, error mapping."""

from __future__ import annotations

from gaia.llm.mock_provider import MOCK_COURSE_MODULES

OUTLINE = {
    "modules": [
        {"title": "Foundations", "topics": ["Players and strategies", "Payoff matrices"]},
        {"title": "Equilibria", "topics": ["Nash equilibrium"]},
    ]
}


def _create(client, **body):
    body.setdefault("subject", "Game theory")
    body.setdefault("outline", OUTLINE)
    response = client.post("/api/study/plans", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_with_an_outline_then_list_get_and_delete(client):
    plan = _create(client, goal="read papers")
    assert plan["topic_count"] == 3
    assert plan["mastered_count"] == 0
    assert plan["due_count"] == 0
    assert plan["current_topic"] == "Players and strategies"
    assert plan["level"] is None
    assert [t["topic"] for t in plan["topics"]] == [
        "Players and strategies",
        "Payoff matrices",
        "Nash equilibrium",
    ]
    assert plan["topics"][0]["module"] == "Foundations"

    listed = client.get("/api/study/plans").json()
    assert [p["id"] for p in listed] == [plan["id"]]
    assert client.get(f"/api/study/plans/{plan['id']}").json()["subject"] == "Game theory"

    assert client.delete(f"/api/study/plans/{plan['id']}").status_code == 204
    assert client.get(f"/api/study/plans/{plan['id']}").status_code == 404
    assert client.delete(f"/api/study/plans/{plan['id']}").status_code == 404


def test_create_without_an_outline_generates_one_with_the_configured_model(mock_client):
    response = mock_client.post(
        "/api/study/plans", json={"subject": "Game theory", "level": "beginner"}
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["outline"] == {"modules": MOCK_COURSE_MODULES}
    assert plan["level"] == "beginner"


def test_generation_with_an_unusable_reply_is_a_readable_400_and_stores_nothing(
    mock_client, monkeypatch
):
    from gaia.llm.base import StreamEvent
    from gaia.llm.mock_provider import MockProvider

    async def prose(self, messages, **kwargs):
        yield StreamEvent(type="text", text="Game theory is about strategy.")
        yield StreamEvent(type="done", stop_reason="end_turn")

    monkeypatch.setattr(MockProvider, "stream_chat", prose)
    response = mock_client.post("/api/study/plans", json={"subject": "Game theory"})
    assert response.status_code == 400
    assert "course outline" in response.json()["detail"]
    assert mock_client.get("/api/study/plans").json() == []


def test_generation_when_the_provider_fails_is_a_readable_502(mock_client, monkeypatch):
    from gaia.llm.base import ProviderUnavailable
    from gaia.llm.mock_provider import MockProvider

    async def unreachable(self, messages, **kwargs):
        raise ProviderUnavailable("Could not reach the model.", remedy="Is it running?")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(MockProvider, "stream_chat", unreachable)
    response = mock_client.post("/api/study/plans", json={"subject": "Game theory"})
    assert response.status_code == 502
    assert response.json()["detail"] == "Could not reach the model. Is it running?"


def test_invalid_input_is_a_400_not_a_500(client):
    bad_outline = client.post("/api/study/plans", json={"subject": "X", "outline": {"modules": []}})
    assert bad_outline.status_code == 400
    bad_level = client.post(
        "/api/study/plans", json={"subject": "X", "outline": OUTLINE, "level": "expert"}
    )
    assert bad_level.status_code == 400


def test_patch_level_goal_and_active(client):
    plan = _create(client)
    updated = client.patch(
        f"/api/study/plans/{plan['id']}", json={"level": "advanced", "goal": "research"}
    ).json()
    assert updated["level"] == "advanced"
    assert updated["goal"] == "research"

    assert client.patch(f"/api/study/plans/{plan['id']}", json={"level": "x"}).status_code == 400

    client.patch(f"/api/study/plans/{plan['id']}", json={"active": False})
    assert client.get("/api/study/plans").json() == []
    assert len(client.get("/api/study/plans?include_inactive=true").json()) == 1


def test_self_graded_review_then_reset(client):
    plan = _create(client)
    after = client.post(
        f"/api/study/plans/{plan['id']}/reviews", json={"topic": "Payoff matrices", "score": 5}
    ).json()
    topic = next(t for t in after["topics"] if t["topic"] == "Payoff matrices")
    assert topic["attempts"] == 1
    assert topic["mastery"] == 1.0
    assert topic["next_review_at"] is not None

    unknown = client.post(
        f"/api/study/plans/{plan['id']}/reviews", json={"topic": "Nope", "score": 3}
    )
    assert unknown.status_code == 400
    out_of_range = client.post(
        f"/api/study/plans/{plan['id']}/reviews", json={"topic": "Payoff matrices", "score": 9}
    )
    assert out_of_range.status_code == 422

    reset = client.post(f"/api/study/plans/{plan['id']}/reset").json()
    assert all(t["attempts"] == 0 for t in reset["topics"])


def test_starting_a_session_creates_a_linked_conversation(client):
    plan = _create(client)
    conversation = client.post(f"/api/study/plans/{plan['id']}/sessions")
    assert conversation.status_code == 201
    body = conversation.json()
    assert body["study_plan_id"] == plan["id"]
    assert body["title"] == "Study: Game theory"

    refreshed = client.get(f"/api/study/plans/{plan['id']}").json()
    assert refreshed["latest_conversation_id"] == body["id"]
    assert client.post("/api/study/plans/nope/sessions").status_code == 404


def test_conversation_patch_attaches_detaches_and_rejects_an_unknown_course(client):
    plan = _create(client)
    conversation_id = client.post("/api/conversations", json={}).json()["id"]

    attached = client.patch(
        f"/api/conversations/{conversation_id}", json={"study_plan_id": plan["id"]}
    )
    assert attached.json()["study_plan_id"] == plan["id"]

    unknown = client.patch(f"/api/conversations/{conversation_id}", json={"study_plan_id": "nope"})
    assert unknown.status_code == 404

    detached = client.patch(f"/api/conversations/{conversation_id}", json={"study_plan_id": None})
    assert detached.json()["study_plan_id"] is None
