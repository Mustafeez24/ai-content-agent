import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ContentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day_number: int
    date: date
    platform: str
    content_type: str
    package_type: str
    topic: str
    objective: str
    target_audience: str
    content_angle: str
    priority: str
    hook: str
    script_scenes: list[str]
    slides: list[str]
    frames: list[str]
    interaction_suggestion: str
    headline: str
    body: str
    caption: str
    cta: str
    footage_note: str
    evidence_basis: str
    evidence_type: str
    source_post_ids: list[str]
    confidence: str
    requires_verification: bool
    verification_reason: Optional[str] = None
    ai_status: str
    workflow_status: str
    created_at: datetime
    updated_at: datetime


class ContentListResponse(BaseModel):
    items: list[ContentItemOut]
    total: int
    page: int
    limit: int


class StatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None
    changed_by: Optional[str] = None


class NoteCreate(BaseModel):
    note: str
    author: Optional[str] = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_item_id: uuid.UUID
    author: str
    note: str
    created_at: datetime
