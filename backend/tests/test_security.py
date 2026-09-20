from tests.conftest import AUTH_HEADERS, persist_item


def test_status_update_rejected_without_secret(client, db_session):
    item = persist_item(db_session)
    resp = client.patch(f"/api/content/{item.id}/status", json={"status": "Approved"})
    assert resp.status_code == 401


def test_status_update_rejected_with_wrong_secret(client, db_session):
    item = persist_item(db_session)
    resp = client.patch(f"/api/content/{item.id}/status", json={"status": "Approved"}, headers={"X-API-Secret": "wrong"})
    assert resp.status_code == 401


def test_status_update_allowed_with_correct_secret(client, db_session):
    item = persist_item(db_session)
    resp = client.patch(f"/api/content/{item.id}/status", json={"status": "Approved"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["workflow_status"] == "Approved"


def test_notes_endpoint_rejected_without_secret(client, db_session):
    item = persist_item(db_session)
    resp = client.post(f"/api/content/{item.id}/notes", json={"note": "hello"})
    assert resp.status_code == 401


def test_notes_endpoint_allowed_with_secret(client, db_session):
    item = persist_item(db_session)
    resp = client.post(f"/api/content/{item.id}/notes", json={"note": "hello", "author": "editor1"}, headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["note"] == "hello"


def test_imports_run_rejected_without_secret(client):
    resp = client.post("/api/imports/run")
    assert resp.status_code == 401


def test_read_endpoints_do_not_require_secret(client):
    resp = client.get("/api/content")
    assert resp.status_code == 200
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200


def test_unconfigured_secret_fails_closed(client, monkeypatch):
    from app import security

    monkeypatch.setattr(security.settings, "content_agent_api_secret", None)
    resp = client.post("/api/content/00000000-0000-0000-0000-000000000000/notes", json={"note": "x"})
    assert resp.status_code == 503
