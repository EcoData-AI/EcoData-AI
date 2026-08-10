from __future__ import annotations


def test_create_list_and_fetch(client):
    created = client.post("/api/conversations", json={"title": "Nash equilibrium"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listing = client.get("/api/conversations")
    assert listing.status_code == 200
    assert [c["id"] for c in listing.json()] == [conversation_id]

    detail = client.get(f"/api/conversations/{conversation_id}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Nash equilibrium"
    assert detail.json()["messages"] == []


def test_rename_pin_and_delete(client):
    conversation_id = client.post("/api/conversations", json={}).json()["id"]

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Oligopoly"})
    assert renamed.json()["title"] == "Oligopoly"

    pinned = client.patch(f"/api/conversations/{conversation_id}", json={"pinned": True})
    assert pinned.json()["pinned"] is True

    # A partial update must not reset the fields it does not mention.
    assert pinned.json()["title"] == "Oligopoly"

    unpinned = client.patch(f"/api/conversations/{conversation_id}", json={"pinned": False})
    assert unpinned.json()["pinned"] is False

    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_search_matches_titles_and_message_bodies(mock_client):
    first = mock_client.post("/api/conversations", json={"title": "Cournot duopoly"}).json()["id"]
    second = mock_client.post("/api/conversations", json={"title": "Unrelated"}).json()["id"]

    with mock_client.stream(
        "POST", "/api/chat", json={"conversation_id": second, "content": "tell me about Bertrand"}
    ) as response:
        assert response.status_code == 200
        list(response.iter_lines())

    by_title = mock_client.get("/api/conversations", params={"q": "Cournot"}).json()
    assert [c["id"] for c in by_title] == [first]

    by_body = mock_client.get("/api/conversations", params={"q": "Bertrand"}).json()
    assert [c["id"] for c in by_body] == [second]


def test_archived_conversations_are_hidden_by_default(client):
    conversation_id = client.post("/api/conversations", json={}).json()["id"]
    client.patch(f"/api/conversations/{conversation_id}", json={"archived": True})

    assert client.get("/api/conversations").json() == []
    assert len(client.get("/api/conversations", params={"include_archived": True}).json()) == 1


def test_missing_conversation_returns_404(client):
    assert client.get("/api/conversations/does-not-exist").status_code == 404
    assert client.patch("/api/conversations/nope", json={"title": "x"}).status_code == 404
    assert client.delete("/api/conversations/nope").status_code == 404
