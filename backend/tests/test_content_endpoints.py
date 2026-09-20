from tests.conftest import AUTH_HEADERS, persist_item


def test_list_content_returns_items(client, db_session):
    persist_item(db_session, day_number=1)
    persist_item(db_session, day_number=2)
    resp = client.get("/api/content")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_content_filters_by_platform(client, db_session):
    persist_item(db_session, day_number=1, platform="Instagram")
    persist_item(db_session, day_number=2, platform="Google Business Profile")
    resp = client.get("/api/content", params={"platform": "Google Business Profile"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["platform"] == "Google Business Profile"


def test_list_content_filters_by_status(client, db_session):
    persist_item(db_session, day_number=1, workflow_status="QA Passed")
    persist_item(db_session, day_number=2, workflow_status="Approved")
    resp = client.get("/api/content", params={"status": "Approved"})
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["workflow_status"] == "Approved"


def test_list_content_searches_topic(client, db_session):
    persist_item(db_session, day_number=1, topic="Marine life spotting in Goa")
    persist_item(db_session, day_number=2, topic="Beginner scuba checklist")
    resp = client.get("/api/content", params={"q": "marine life"})
    body = resp.json()
    assert body["total"] == 1
    assert "Marine life" in body["items"][0]["topic"]


def test_list_content_ordered_by_day_number(client, db_session):
    persist_item(db_session, day_number=3)
    persist_item(db_session, day_number=1)
    persist_item(db_session, day_number=2)
    resp = client.get("/api/content")
    day_numbers = [item["day_number"] for item in resp.json()["items"]]
    assert day_numbers == [1, 2, 3]


def test_get_content_detail(client, db_session):
    item = persist_item(db_session, day_number=1, hook="A specific hook")
    resp = client.get(f"/api/content/{item.id}")
    assert resp.status_code == 200
    assert resp.json()["hook"] == "A specific hook"


def test_get_content_detail_404(client):
    resp = client.get("/api/content/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_status_update_rejects_invalid_status(client, db_session):
    item = persist_item(db_session)
    resp = client.patch(f"/api/content/{item.id}/status", json={"status": "Not A Real Status"}, headers=AUTH_HEADERS)
    assert resp.status_code == 422


def test_status_update_records_history(client, db_session):
    from app.models.content_status_history import ContentStatusHistory

    item = persist_item(db_session)
    client.patch(f"/api/content/{item.id}/status", json={"status": "Pending Review"}, headers=AUTH_HEADERS)
    client.patch(
        f"/api/content/{item.id}/status",
        json={"status": "Changes Requested", "reason": "CTA too generic"},
        headers=AUTH_HEADERS,
    )
    history = (
        db_session.query(ContentStatusHistory)
        .filter(ContentStatusHistory.content_item_id == item.id)
        .order_by(ContentStatusHistory.changed_at)
        .all()
    )
    assert len(history) == 2
    assert history[0].to_status == "Pending Review"
    assert history[1].to_status == "Changes Requested"
    assert history[1].from_status == "Pending Review"
    assert history[1].reason == "CTA too generic"


def test_add_and_list_notes(client, db_session):
    item = persist_item(db_session)
    client.post(f"/api/content/{item.id}/notes", json={"note": "First note", "author": "alice"}, headers=AUTH_HEADERS)
    client.post(f"/api/content/{item.id}/notes", json={"note": "Second note", "author": "bob"}, headers=AUTH_HEADERS)
    resp = client.get(f"/api/content/{item.id}/notes")
    assert resp.status_code == 200
    notes = resp.json()
    assert len(notes) == 2
    assert notes[0]["note"] == "First note"
    assert notes[1]["author"] == "bob"
