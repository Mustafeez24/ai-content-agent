from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content_item import WORKFLOW_STATUSES, ContentItem
from app.models.content_note import ContentNote
from app.models.content_status_history import ContentStatusHistory
from app.schemas.content import ContentItemOut, ContentListResponse, NoteCreate, NoteOut, StatusUpdate
from app.security import require_api_secret

router = APIRouter(prefix="/api/content", tags=["content"])


@router.get("", response_model=ContentListResponse)
def list_content(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    platform: Optional[str] = None,
    content_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(ContentItem)
    if date_from is not None:
        query = query.filter(ContentItem.date >= date_from)
    if date_to is not None:
        query = query.filter(ContentItem.date <= date_to)
    if platform:
        query = query.filter(ContentItem.platform == platform)
    if content_type:
        query = query.filter(ContentItem.content_type == content_type)
    if status:
        query = query.filter(ContentItem.workflow_status == status)
    if priority:
        query = query.filter(ContentItem.priority == priority)
    if q:
        query = query.filter(ContentItem.topic.ilike(f"%{q}%"))

    total = query.count()
    items = query.order_by(ContentItem.day_number).offset((page - 1) * limit).limit(limit).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/{content_id}", response_model=ContentItemOut)
def get_content(content_id: UUID, db: Session = Depends(get_db)):
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found.")
    return item


@router.patch("/{content_id}/status", response_model=ContentItemOut, dependencies=[Depends(require_api_secret)])
def update_status(content_id: UUID, payload: StatusUpdate, db: Session = Depends(get_db)):
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found.")
    if payload.status not in WORKFLOW_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {list(WORKFLOW_STATUSES)}")

    history = ContentStatusHistory(
        content_item_id=item.id,
        from_status=item.workflow_status,
        to_status=payload.status,
        changed_by=payload.changed_by,
        reason=payload.reason,
    )
    db.add(history)
    item.workflow_status = payload.status
    db.commit()
    db.refresh(item)
    return item


@router.get("/{content_id}/notes", response_model=list[NoteOut])
def list_notes(content_id: UUID, db: Session = Depends(get_db)):
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found.")
    return (
        db.query(ContentNote)
        .filter(ContentNote.content_item_id == content_id)
        .order_by(ContentNote.created_at)
        .all()
    )


@router.post("/{content_id}/notes", response_model=NoteOut, dependencies=[Depends(require_api_secret)])
def add_note(content_id: UUID, payload: NoteCreate, db: Session = Depends(get_db)):
    item = db.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content item not found.")
    note = ContentNote(content_item_id=content_id, author=payload.author or "unknown", note=payload.note)
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
