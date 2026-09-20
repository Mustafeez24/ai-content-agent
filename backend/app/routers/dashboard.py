from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_item import ContentItem
from app.models.pipeline_run import PipelineRun

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db)):
    total = db.query(func.count(ContentItem.id)).scalar() or 0

    status_counts = dict(
        db.query(ContentItem.workflow_status, func.count(ContentItem.id)).group_by(ContentItem.workflow_status).all()
    )
    platform_counts = dict(
        db.query(ContentItem.platform, func.count(ContentItem.id)).group_by(ContentItem.platform).all()
    )
    content_type_counts = dict(
        db.query(ContentItem.content_type, func.count(ContentItem.id)).group_by(ContentItem.content_type).all()
    )

    latest_run = db.query(PipelineRun).order_by(PipelineRun.imported_at.desc()).first()
    qa_warning_count = len(latest_run.qa_warnings) if latest_run else 0

    return {
        "total_content_items": total,
        "ai_generated": status_counts.get("AI Generated", 0),
        "qa_passed": status_counts.get("QA Passed", 0),
        "pending_review": status_counts.get("Pending Review", 0),
        "changes_requested": status_counts.get("Changes Requested", 0),
        "approved": status_counts.get("Approved", 0),
        "scheduled": status_counts.get("Scheduled", 0),
        "published": status_counts.get("Published", 0),
        "qa_warnings": qa_warning_count,
        "platform_breakdown": platform_counts,
        "content_type_breakdown": content_type_counts,
        "latest_pipeline_run_id": str(latest_run.id) if latest_run else None,
    }
