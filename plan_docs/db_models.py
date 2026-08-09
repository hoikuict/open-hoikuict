from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from time_utils import utc_now


class PlanDocumentRow(SQLModel, table=True):
    __tablename__ = "plan_documents"
    __table_args__ = (
        UniqueConstraint("document_type", "child_id", "target_month", name="uq_plan_document_child_month"),
        UniqueConstraint(
            "document_type",
            "child_id",
            "record_cycle_key",
            name="uq_plan_document_child_cycle_constraint",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_type: str = Field(index=True)
    status: str = Field(index=True)
    title: str
    nursery_ref: str
    classroom_ref: str = Field(index=True)
    actor_ref: Optional[str] = None
    owner_name: str
    school_year: Optional[int] = Field(default=None, index=True)
    target_month: Optional[str] = None
    target_week: Optional[str] = None
    week_start_date: Optional[str] = None
    target_date: Optional[str] = None
    period_start: Optional[str] = Field(default=None, index=True)
    period_end: Optional[str] = Field(default=None, index=True)
    record_cycle_key: Optional[str] = Field(default=None, index=True)
    setting_version_id: Optional[int] = Field(
        default=None,
        foreign_key="child_record_setting_versions.id",
        index=True,
    )
    age_class: Optional[str] = None
    child_id: Optional[int] = Field(default=None, foreign_key="children.id", index=True)
    child_ref: Optional[str] = None
    child_name: Optional[str] = None
    parent_document_id: Optional[int] = None
    related_document_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    sections: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    schedule: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    confirmation_items: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PlanDocumentAction(SQLModel, table=True):
    __tablename__ = "plan_document_actions"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    document_type: str
    action: str
    comment: Optional[str] = None
    actor_ref: str
    created_at: datetime = Field(default_factory=utc_now)


class PlanReviewNotificationRow(SQLModel, table=True):
    __tablename__ = "plan_review_notifications"
    __table_args__ = (
        UniqueConstraint(
            "review_revision_id",
            "recipient_user_id",
            name="uq_plan_review_notification_recipient_revision",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    review_revision_id: int = Field(foreign_key="plan_revisions.id", index=True)
    recipient_user_id: UUID = Field(foreign_key="users.id", index=True)
    nursery_ref: str = Field(index=True)
    document_title: str
    requested_by_ref: str
    requested_by_name: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
    read_at: Optional[datetime] = Field(default=None, index=True)
    resolved_at: Optional[datetime] = Field(default=None, index=True)


class PlanDailyReflectionRow(SQLModel, table=True):
    __tablename__ = "plan_daily_reflections"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_plan_daily_reflection_document"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    body: str = Field(default="")
    status: str = Field(default="draft", index=True)
    updated_by: str
    updated_at: datetime = Field(default_factory=utc_now)
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = Field(default=None, index=True)


class PlanDocumentHeadRow(SQLModel, table=True):
    __tablename__ = "plan_document_heads"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_plan_document_head_document"),
        UniqueConstraint("public_id", name="uq_plan_document_head_public_id"),
        UniqueConstraint(
            "nursery_ref",
            "classroom_ref",
            "target_date",
            "plan_scope_key",
            name="uq_daily_plan_scope",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    public_id: str = Field(default_factory=lambda: str(uuid4()), index=True)
    nursery_ref: str = Field(index=True)
    classroom_ref: str = Field(index=True)
    target_date: Optional[str] = Field(default=None, index=True)
    plan_scope_key: str = Field(default="main")
    current_revision_id: Optional[int] = Field(default=None, index=True)
    review_revision_id: Optional[int] = Field(default=None, index=True)
    approved_revision_id: Optional[int] = Field(default=None, index=True)
    template_version_id: Optional[int] = Field(default=None, index=True)
    lock_version: int = Field(default=1)
    deleted_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PlanRevisionRow(SQLModel, table=True):
    __tablename__ = "plan_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_no", name="uq_plan_revision_number"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    revision_no: int
    payload_schema_version: str = Field(default="1")
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    reason: Optional[str] = None
    content_hash: str = Field(index=True)
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)


class PlanExecutionChangeRow(SQLModel, table=True):
    __tablename__ = "plan_execution_changes"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="plan_documents.id", index=True)
    base_revision_id: int = Field(foreign_key="plan_revisions.id", index=True)
    approval_state_at_change: str = Field(index=True)
    affected_block_key: Optional[str] = Field(default=None, index=True)
    reason_code: str = Field(index=True)
    reason_note: Optional[str] = None
    impact_level: str = Field(index=True)
    before_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    after_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    changed_at: datetime
    recorded_by: str
    recorded_at: datetime = Field(default_factory=utc_now)
    confirmation_status: str = Field(default="not_required", index=True)
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    confirmation_comment: Optional[str] = None
    corrects_change_id: Optional[int] = Field(
        default=None,
        foreign_key="plan_execution_changes.id",
        index=True,
    )

