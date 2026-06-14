from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from time_utils import utc_now


class PlanDocumentRow(SQLModel, table=True):
    __tablename__ = "plan_documents"
    __table_args__ = (
        UniqueConstraint("document_type", "child_id", "target_month", name="uq_plan_document_child_month"),
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

