import os
import sys
from pathlib import Path

# Point the app at a dedicated test database and a known test secret BEFORE any
# app.* module is imported (Settings() reads the environment once, at import time).
TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/content_agent_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CONTENT_AGENT_API_SECRET"] = "test-secret-for-pytest"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers every model on Base.metadata)
from app.database import Base, engine, get_db
from app.main import app

TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session():
    """Per-test isolation via an outer transaction + a restarted SAVEPOINT, so that
    an inner service.commit() (e.g. import_publish_ready_export's own db.commit())
    does not end the outer transaction early - the standard SQLAlchemy 2.0 pattern
    for testing code that calls commit() itself."""
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


API_SECRET = "test-secret-for-pytest"
AUTH_HEADERS = {"X-API-Secret": API_SECRET}


def make_content_item_dict(day_number=1, **overrides) -> dict:
    """A single content_items entry matching Stage 10's exact 27-field contract."""
    base = {
        "day_number": day_number,
        "date": f"2026-01-{day_number:02d}",
        "platform": "Instagram",
        "content_type": "Reel",
        "package_type": "reel",
        "topic": f"Distinct topic {day_number} about scuba diving in Goa",
        "objective": "Educational",
        "target_audience": "First-time divers",
        "content_angle": "Simple beginner education",
        "priority": "medium",
        "hook": f"Hook for day {day_number}",
        "script_scenes": ["Scene 1: boat footage", "Scene 2: instructor briefing"],
        "slides": [],
        "frames": [],
        "interaction_suggestion": "",
        "headline": "",
        "body": "",
        "caption": f"Caption for day {day_number}",
        "cta": "DM us to learn more",
        "footage_note": "Use existing FlyingFish footage if available.",
        "evidence_basis": "POST_TOP1 had 3,200 likes and included instructor praise.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": None,
        "status": "drafted",
    }
    base.update(overrides)
    return base


def persist_item(db_session, day_number=1, workflow_status="QA Passed", **overrides):
    """Create and commit one PipelineRun + ContentItem pair for a test - reduces the
    boilerplate every endpoint test would otherwise repeat."""
    from app.models.content_item import ContentItem
    from app.models.pipeline_run import PipelineRun

    run = PipelineRun(qa_status="PASS", days_imported=1, qa_warnings=[])
    db_session.add(run)
    db_session.flush()

    fields = {
        "pipeline_run_id": run.id,
        "day_number": day_number,
        "date": f"2026-01-{day_number:02d}",
        "platform": "Instagram",
        "content_type": "Reel",
        "package_type": "reel",
        "topic": f"Distinct topic {day_number} about scuba diving in Goa",
        "objective": "Educational",
        "target_audience": "First-time divers",
        "content_angle": "Simple beginner education",
        "priority": "medium",
        "hook": f"Hook for day {day_number}",
        "script_scenes": ["Scene 1", "Scene 2"],
        "slides": [],
        "frames": [],
        "interaction_suggestion": "",
        "headline": "",
        "body": "",
        "caption": f"Caption for day {day_number}",
        "cta": "DM us to learn more",
        "footage_note": "Use existing FlyingFish footage if available.",
        "evidence_basis": "POST_TOP1 had 3,200 likes.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": None,
        "ai_status": "drafted",
        "workflow_status": workflow_status,
    }
    fields.update(overrides)
    item = ContentItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_publish_ready_export(days=3, qa_status="PASS", qa_warnings=None) -> dict:
    """A full flyingfish_publish_ready.json - Stage 10's exact output shape."""
    return {
        "metadata": {
            "agent": "content_export",
            "qa_source": "data/instagram/flyingfish_content_qa.json",
            "content_source": "data/instagram/flyingfish_content.json",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "qa_status": qa_status,
            "days_exported": days,
        },
        "qa_summary": {"hard_failure_count": 0, "warning_count": len(qa_warnings or []), "days_expected": days, "days_covered": days},
        "qa_warnings": qa_warnings or [],
        "export_notes": [],
        "content_items": [make_content_item_dict(day_number=i) for i in range(1, days + 1)],
    }
