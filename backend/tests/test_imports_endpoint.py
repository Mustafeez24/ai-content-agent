import json
import tempfile
from pathlib import Path

from tests.conftest import AUTH_HEADERS, make_publish_ready_export


def test_run_import_endpoint_succeeds(client, db_session, monkeypatch):
    from app import config

    data = make_publish_ready_export(days=3)
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()

    monkeypatch.setattr(config.settings, "stage10_export_path", f.name)
    import app.routers.imports as imports_router

    monkeypatch.setattr(imports_router.settings, "stage10_export_path", f.name)

    resp = client.post("/api/imports/run", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported_or_updated"] == 3
    assert body["skipped_protected"] == []


def test_run_import_endpoint_rejects_qa_fail(client, monkeypatch):
    from app import config
    import app.routers.imports as imports_router

    data = make_publish_ready_export(days=2, qa_status="FAIL")
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()

    monkeypatch.setattr(imports_router.settings, "stage10_export_path", f.name)

    resp = client.post("/api/imports/run", headers=AUTH_HEADERS)
    assert resp.status_code == 400
    assert "PASS" in resp.json()["detail"]


def test_run_import_endpoint_missing_file(client, monkeypatch):
    import app.routers.imports as imports_router

    monkeypatch.setattr(imports_router.settings, "stage10_export_path", "/tmp/does-not-exist-publish-ready.json")
    resp = client.post("/api/imports/run", headers=AUTH_HEADERS)
    assert resp.status_code == 400
