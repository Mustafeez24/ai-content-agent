from tests.conftest import persist_item


def test_dashboard_summary_counts(client, db_session):
    persist_item(db_session, day_number=1, workflow_status="QA Passed", platform="Instagram", content_type="Reel")
    persist_item(db_session, day_number=2, workflow_status="Pending Review", platform="Instagram", content_type="Carousel")
    persist_item(db_session, day_number=3, workflow_status="Approved", platform="Google Business Profile", content_type="Static Post")
    persist_item(db_session, day_number=4, workflow_status="Scheduled", platform="Instagram", content_type="Reel")
    persist_item(db_session, day_number=5, workflow_status="Published", platform="Instagram", content_type="Story")

    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total_content_items"] == 5
    assert body["pending_review"] == 1
    assert body["approved"] == 1
    assert body["scheduled"] == 1
    assert body["published"] == 1
    assert body["qa_passed"] == 1
    assert body["platform_breakdown"]["Instagram"] == 4
    assert body["platform_breakdown"]["Google Business Profile"] == 1
    assert body["content_type_breakdown"]["Reel"] == 2


def test_dashboard_summary_qa_warnings_from_latest_run(client, db_session):
    from app.models.pipeline_run import PipelineRun

    persist_item(db_session, day_number=1)
    run = PipelineRun(qa_status="PASS", days_imported=1, qa_warnings=["warning one", "warning two"])
    db_session.add(run)
    db_session.commit()

    resp = client.get("/api/dashboard/summary")
    assert resp.json()["qa_warnings"] == 2


def test_dashboard_summary_empty_database(client):
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    assert resp.json()["total_content_items"] == 0
