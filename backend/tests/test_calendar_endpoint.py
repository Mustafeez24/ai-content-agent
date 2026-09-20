from tests.conftest import persist_item


def test_calendar_groups_items_by_date(client, db_session):
    persist_item(db_session, day_number=1, date="2026-01-01")
    persist_item(db_session, day_number=2, date="2026-01-02")
    persist_item(db_session, day_number=15, date="2026-02-15")  # outside January

    resp = client.get("/api/calendar", params={"month": "2026-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["days"].keys()) == {"2026-01-01", "2026-01-02"}


def test_calendar_invalid_month_rejected(client):
    resp = client.get("/api/calendar", params={"month": "not-a-month"})
    assert resp.status_code == 422


def test_calendar_day_entry_includes_key_fields(client, db_session):
    persist_item(db_session, day_number=1, date="2026-01-01", platform="Instagram", content_type="Reel", topic="A topic")
    resp = client.get("/api/calendar", params={"month": "2026-01"})
    entry = resp.json()["days"]["2026-01-01"][0]
    assert entry["platform"] == "Instagram"
    assert entry["content_type"] == "Reel"
    assert entry["topic"] == "A topic"
    assert "workflow_status" in entry
