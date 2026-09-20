"""Initial Stage 11 schema: pipeline_runs, content_items, content_status_history,
content_notes, users.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("qa_status", sa.String(), nullable=False),
        sa.Column("days_imported", sa.Integer(), nullable=False),
        sa.Column("qa_source_path", sa.String(), nullable=False, server_default=""),
        sa.Column("content_source_path", sa.String(), nullable=False, server_default=""),
        sa.Column("qa_warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "content_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_runs.id"), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("package_type", sa.String(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("target_audience", sa.Text(), nullable=False),
        sa.Column("content_angle", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False, server_default=""),
        sa.Column("script_scenes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("slides", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("frames", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("interaction_suggestion", sa.Text(), nullable=False, server_default=""),
        sa.Column("headline", sa.Text(), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("cta", sa.Text(), nullable=False, server_default=""),
        sa.Column("footage_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_basis", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("source_post_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("requires_verification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_reason", sa.Text(), nullable=True),
        sa.Column("ai_status", sa.String(), nullable=False),
        sa.Column("workflow_status", sa.String(), nullable=False, server_default="QA Passed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("day_number", name="uq_content_items_day_number"),
    )
    op.create_index("ix_content_items_workflow_status", "content_items", ["workflow_status"])
    op.create_index("ix_content_items_date", "content_items", ["date"])
    op.create_index("ix_content_items_platform", "content_items", ["platform"])

    op.create_table(
        "content_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id"), nullable=False),
        sa.Column("from_status", sa.String(), nullable=True),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_content_status_history_content_item_id", "content_status_history", ["content_item_id"])

    op.create_table(
        "content_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id"), nullable=False),
        sa.Column("author", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_content_notes_content_item_id", "content_notes", ["content_item_id"])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("users")
    op.drop_index("ix_content_notes_content_item_id", table_name="content_notes")
    op.drop_table("content_notes")
    op.drop_index("ix_content_status_history_content_item_id", table_name="content_status_history")
    op.drop_table("content_status_history")
    op.drop_index("ix_content_items_platform", table_name="content_items")
    op.drop_index("ix_content_items_date", table_name="content_items")
    op.drop_index("ix_content_items_workflow_status", table_name="content_items")
    op.drop_table("content_items")
    op.drop_table("pipeline_runs")
