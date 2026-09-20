import uuid
from datetime import date as date_type, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Exactly the team workflow statuses from the approved Stage 11 architecture - a
# fresh import always lands on "QA Passed" (Stage 9 already gated it); everything
# after that is a human decision.
WORKFLOW_STATUSES = (
    "AI Generated",
    "QA Passed",
    "Pending Review",
    "Changes Requested",
    "Approved",
    "Scheduled",
    "Published",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentItem(Base):
    """One row per calendar day - day_number is globally unique (matching Stage 7/8/9's
    own "exactly one item per day" invariant). Re-importing a newer Stage 10 export
    updates this row in place UNLESS its workflow_status has already moved past
    "QA Passed" (see app/services/import_service.py), so a human decision is never
    silently overwritten."""

    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("day_number", name="uq_content_items_day_number"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)

    # Carried forward from Stage 7 via Stage 8/10, exactly as generated - never
    # regenerated or altered by this backend.
    day_number: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    package_type: Mapped[str] = mapped_column(String, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    target_audience: Mapped[str] = mapped_column(Text, nullable=False)
    content_angle: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False)

    hook: Mapped[str] = mapped_column(Text, nullable=False, default="")
    script_scenes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    slides: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    frames: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    interaction_suggestion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    headline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    caption: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cta: Mapped[str] = mapped_column(Text, nullable=False, default="")
    footage_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    evidence_basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_type: Mapped[str] = mapped_column(String, nullable=False)
    source_post_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    requires_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stage 8's own "status" field (e.g. "drafted"), preserved verbatim and never
    # confused with workflow_status below.
    ai_status: Mapped[str] = mapped_column(String, nullable=False)
    workflow_status: Mapped[str] = mapped_column(String, nullable=False, default="QA Passed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    pipeline_run = relationship("PipelineRun", back_populates="content_items")
    status_history = relationship(
        "ContentStatusHistory", back_populates="content_item", cascade="all, delete-orphan"
    )
    notes = relationship("ContentNote", back_populates="content_item", cascade="all, delete-orphan")
