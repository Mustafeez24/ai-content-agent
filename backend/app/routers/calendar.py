import calendar as pycalendar
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_item import ContentItem

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("")
def get_calendar_month(month: str = Query(..., description="YYYY-MM"), db: Session = Depends(get_db)):
    try:
        year_str, month_str = month.split("-")
        year, mon = int(year_str), int(month_str)
        first_day = date_type(year, mon, 1)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="month must be in YYYY-MM format.")

    last_day_num = pycalendar.monthrange(year, mon)[1]
    last_day = date_type(year, mon, last_day_num)

    items = (
        db.query(ContentItem)
        .filter(ContentItem.date >= first_day, ContentItem.date <= last_day)
        .order_by(ContentItem.date)
        .all()
    )

    days: dict = {}
    for item in items:
        key = item.date.isoformat()
        days.setdefault(key, []).append(
            {
                "id": str(item.id),
                "day_number": item.day_number,
                "platform": item.platform,
                "content_type": item.content_type,
                "package_type": item.package_type,
                "topic": item.topic,
                "priority": item.priority,
                "workflow_status": item.workflow_status,
            }
        )

    return {"month": month, "days": days}
