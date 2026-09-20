import csv
import io
import json

from tests.conftest import persist_item


def test_json_export_matches_database(client, db_session):
    persist_item(db_session, day_number=1, topic="Topic one")
    persist_item(db_session, day_number=2, topic="Topic two")
    resp = client.get("/api/exports/json")
    assert resp.status_code == 200
    data = json.loads(resp.text)
    assert len(data["content_items"]) == 2
    assert [it["day_number"] for it in data["content_items"]] == [1, 2]
    assert data["content_items"][0]["topic"] == "Topic one"


def test_csv_export_has_expected_columns(client, db_session):
    persist_item(db_session, day_number=1)
    resp = client.get("/api/exports/csv")
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert "day_number" in rows[0]
    assert "topic" in rows[0]
    assert "cta" in rows[0]


def test_markdown_export_contains_day_headers(client, db_session):
    persist_item(db_session, day_number=1, date="2026-01-01")
    resp = client.get("/api/exports/markdown")
    assert resp.status_code == 200
    assert "## Day 1" in resp.text
    assert "2026-01-01" in resp.text


def test_unsupported_format_rejected(client, db_session):
    persist_item(db_session, day_number=1)
    resp = client.get("/api/exports/pdf")
    assert resp.status_code == 404


def test_export_with_no_content_returns_404(client):
    resp = client.get("/api/exports/json")
    assert resp.status_code == 404
