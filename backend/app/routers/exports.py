from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_item import ContentItem
from app.services.export_service import SUPPORTED_FORMATS, build_export

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.get("/{export_format}")
def export_content(export_format: str, db: Session = Depends(get_db)):
    if export_format not in SUPPORTED_FORMATS:
        raise HTTPException(status_code=404, detail=f"Unsupported export format. Supported: {list(SUPPORTED_FORMATS)}")

    items = db.query(ContentItem).order_by(ContentItem.day_number).all()
    if not items:
        raise HTTPException(status_code=404, detail="No content available to export.")

    content, media_type, filename = build_export(items, export_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
