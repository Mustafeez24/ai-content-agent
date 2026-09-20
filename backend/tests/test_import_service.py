import json
import tempfile
from pathlib import Path

import pytest

from app.services.import_service import ContentImportError, import_publish_ready_export, load_publish_ready_export
from tests.conftest import make_publish_ready_export, persist_item


def write_export(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


# --- load_publish_ready_export (validation) ---
def test_missing_file_rejected():
    with pytest.raises(ContentImportError):
        load_publish_ready_export(Path("/tmp/does-not-exist-publish-ready.json"))


def test_invalid_json_rejected():
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    f.write("{not valid json")
    f.close()
    with pytest.raises(ContentImportError):
        load_publish_ready_export(Path(f.name))


def test_missing_top_level_section_rejected():
    path = write_export({"metadata": {"qa_status": "PASS"}})
    with pytest.raises(ContentImportError):
        load_publish_ready_export(path)


def test_qa_status_not_pass_rejected():
    # The QA gate must never be bypassed - even a well-formed export is refused if
    # its own metadata says QA did not pass.
    data = make_publish_ready_export(days=2, qa_status="FAIL")
    path = write_export(data)
    with pytest.raises(ContentImportError, match="not 'PASS'"):
        load_publish_ready_export(path)


def test_missing_item_field_rejected():
    data = make_publish_ready_export(days=1)
    del data["content_items"][0]["evidence_basis"]
    path = write_export(data)
    with pytest.raises(ContentImportError):
        load_publish_ready_export(path)


def test_duplicate_day_number_rejected():
    data = make_publish_ready_export(days=2)
    data["content_items"][1]["day_number"] = 1
    path = write_export(data)
    with pytest.raises(ContentImportError):
        load_publish_ready_export(path)


def test_valid_export_loads():
    data = make_publish_ready_export(days=3)
    path = write_export(data)
    loaded = load_publish_ready_export(path)
    assert len(loaded["content_items"]) == 3


# --- import_publish_ready_export (database effects) ---
def test_fresh_import_creates_items_with_qa_passed(db_session):
    from app.models.content_item import ContentItem

    data = make_publish_ready_export(days=3)
    path = write_export(data)
    result = import_publish_ready_export(db_session, path)

    assert result["imported_or_updated"] == 3
    assert result["skipped_protected"] == []
    items = db_session.query(ContentItem).order_by(ContentItem.day_number).all()
    assert len(items) == 3
    assert all(it.workflow_status == "QA Passed" for it in items)


def test_reimport_updates_items_still_at_qa_passed(db_session):
    from app.models.content_item import ContentItem

    data = make_publish_ready_export(days=2)
    path = write_export(data)
    import_publish_ready_export(db_session, path)

    data2 = make_publish_ready_export(days=2)
    data2["content_items"][0]["topic"] = "A brand new topic after re-import"
    path2 = write_export(data2)
    result = import_publish_ready_export(db_session, path2)

    assert result["imported_or_updated"] == 2
    item = db_session.query(ContentItem).filter(ContentItem.day_number == 1).one()
    assert item.topic == "A brand new topic after re-import"


def test_reimport_never_overwrites_item_past_qa_passed(db_session):
    """The core requirement: a human decision (Approved/Scheduled/etc) must survive
    a re-import untouched, even though the new export has different content for
    that same day_number."""
    from app.models.content_item import ContentItem
    from app.models.pipeline_run import PipelineRun

    data = make_publish_ready_export(days=2)
    path = write_export(data)
    import_publish_ready_export(db_session, path)

    # A human approves day 1.
    approved_item = db_session.query(ContentItem).filter(ContentItem.day_number == 1).one()
    approved_item.workflow_status = "Approved"
    db_session.commit()
    original_topic = approved_item.topic

    # A newer pipeline run comes in with DIFFERENT content for day 1.
    data2 = make_publish_ready_export(days=2)
    data2["content_items"][0]["topic"] = "This must never overwrite the approved item"
    data2["content_items"][0]["hook"] = "This must never overwrite the approved hook"
    path2 = write_export(data2)
    result = import_publish_ready_export(db_session, path2)

    assert result["skipped_protected"] == [{"day_number": 1, "existing_status": "Approved"}]
    assert result["imported_or_updated"] == 1  # only day 2 updated

    db_session.expire_all()
    still_approved = db_session.query(ContentItem).filter(ContentItem.day_number == 1).one()
    assert still_approved.workflow_status == "Approved"
    assert still_approved.topic == original_topic
    assert "must never overwrite" not in still_approved.topic


@pytest.mark.parametrize(
    "protected_status",
    ["Pending Review", "Changes Requested", "Approved", "Scheduled", "Published"],
)
def test_every_protected_status_blocks_reimport(db_session, protected_status):
    from app.models.content_item import ContentItem

    data = make_publish_ready_export(days=1)
    path = write_export(data)
    import_publish_ready_export(db_session, path)

    item = db_session.query(ContentItem).filter(ContentItem.day_number == 1).one()
    item.workflow_status = protected_status
    db_session.commit()

    data2 = make_publish_ready_export(days=1)
    path2 = write_export(data2)
    result = import_publish_ready_export(db_session, path2)

    assert result["skipped_protected"] == [{"day_number": 1, "existing_status": protected_status}]
    db_session.expire_all()
    unchanged = db_session.query(ContentItem).filter(ContentItem.day_number == 1).one()
    assert unchanged.workflow_status == protected_status


def test_pipeline_run_recorded_on_every_import(db_session):
    from app.models.pipeline_run import PipelineRun

    data = make_publish_ready_export(days=2, qa_warnings=["[generic_cta] day 1: something"])
    path = write_export(data)
    import_publish_ready_export(db_session, path)

    run = db_session.query(PipelineRun).order_by(PipelineRun.imported_at.desc()).first()
    assert run.qa_status == "PASS"
    assert run.days_imported == 2
    assert run.qa_warnings == ["[generic_cta] day 1: something"]
