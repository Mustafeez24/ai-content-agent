import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineRun(Base):
    """One row per Stage 10 export ingested into the database - the audit trail for
    where the currently-live content_items rows came from."""

    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    qa_status: Mapped[str] = mapped_column(String, nullable=False)
    days_imported: Mapped[int] = mapped_column(Integer, nullable=False)
    qa_source_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    content_source_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    qa_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    content_items = relationship("ContentItem", back_populates="pipeline_run")
