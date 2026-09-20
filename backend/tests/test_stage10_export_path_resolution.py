"""Regression tests for the Stage 11 Stage-10-export path resolution bug.

Settings.stage10_export_path is a relative string; before this fix, the import
router turned it into a plain relative Path, which resolved against the
process's current working directory instead of the repository root. These
tests prove resolution is anchored to app.config.REPO_ROOT and is unaffected
by os.getcwd(), for both the property itself and the /api/imports/run endpoint.
"""

import json
from pathlib import Path

from tests.conftest import AUTH_HEADERS, make_publish_ready_export


def test_stage10_export_abs_path_ignores_cwd_for_relative_paths(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "stage10_export_path", "data/instagram/exports/flyingfish_publish_ready.json")
    expected = config.REPO_ROOT / "data/instagram/exports/flyingfish_publish_ready.json"

    for cwd in (config.REPO_ROOT, config.REPO_ROOT / "backend", config.REPO_ROOT / "backend" / "app"):
        monkeypatch.chdir(cwd)
        assert config.settings.stage10_export_abs_path == expected


def test_stage10_export_abs_path_leaves_absolute_paths_unchanged(monkeypatch, tmp_path):
    from app import config

    absolute = tmp_path / "somewhere-else" / "publish_ready.json"
    monkeypatch.setattr(config.settings, "stage10_export_path", str(absolute))

    assert config.settings.stage10_export_abs_path == absolute


def _write_fixture_export(repo_root: Path) -> Path:
    """A throwaway export fixture under REPO_ROOT/data/, never the real
    data/instagram/exports/flyingfish_publish_ready.json path - the real
    Stage 10 export is never moved, copied, renamed, or regenerated."""
    fixture_dir = repo_root / "data" / "_test_stage10_export_path_regression"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = fixture_dir / "publish_ready.json"
    fixture_path.write_text(json.dumps(make_publish_ready_export(days=2)))
    return fixture_path


def test_run_import_endpoint_succeeds_when_launched_from_repo_root(client, monkeypatch):
    from app import config
    import app.routers.imports as imports_router

    fixture_path = _write_fixture_export(config.REPO_ROOT)
    try:
        relative_path = fixture_path.relative_to(config.REPO_ROOT)
        monkeypatch.setattr(imports_router.settings, "stage10_export_path", str(relative_path))
        monkeypatch.chdir(config.REPO_ROOT)

        resp = client.post("/api/imports/run", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["imported_or_updated"] == 2
    finally:
        fixture_path.unlink(missing_ok=True)


def test_run_import_endpoint_succeeds_when_launched_from_backend_dir(client, monkeypatch):
    from app import config
    import app.routers.imports as imports_router

    fixture_path = _write_fixture_export(config.REPO_ROOT)
    try:
        relative_path = fixture_path.relative_to(config.REPO_ROOT)
        monkeypatch.setattr(imports_router.settings, "stage10_export_path", str(relative_path))
        monkeypatch.chdir(config.REPO_ROOT / "backend")

        resp = client.post("/api/imports/run", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["imported_or_updated"] == 2
    finally:
        fixture_path.unlink(missing_ok=True)
