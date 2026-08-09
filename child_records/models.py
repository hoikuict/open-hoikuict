from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, Index, UniqueConstraint
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from time_utils import utc_now


class ChildRecordSettingVersion(SQLModel, table=True):
    __tablename__ = "child_record_setting_versions"
    __table_args__ = (
        UniqueConstraint("version_no", name="uq_child_record_setting_version_no"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    version_no: int = Field(index=True)
    status: str = Field(default="active", index=True)
    preset_key: str = Field(default="standard", index=True)
    effective_from: date = Field(index=True)
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    activated_by: Optional[str] = None
    activated_at: Optional[datetime] = None


class ChildObservationLog(SQLModel, table=True):
    __tablename__ = "child_observation_logs"
    __table_args__ = (
        Index("ix_child_observation_logs_child_observed", "child_id", "observed_on"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    public_id: str = Field(default_factory=lambda: str(uuid4()), index=True, unique=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    observed_on: date = Field(index=True)
    child_state: str
    caregiver_support: Optional[str] = None
    reflection: Optional[str] = None
    next_focus: Optional[str] = None
    family_note: Optional[str] = None
    categories: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    perspective_tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    custom_values: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    sensitivity: str = Field(default="normal", index=True)
    setting_version_id: Optional[int] = Field(
        default=None,
        foreign_key="child_record_setting_versions.id",
        index=True,
    )
    classroom_id_snapshot: Optional[int] = Field(default=None, index=True)
    classroom_name_snapshot: Optional[str] = None
    created_by: Optional[str] = Field(default=None, index=True)
    created_by_name: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
    voided_at: Optional[datetime] = Field(default=None, index=True)
    voided_by: Optional[str] = None
    void_reason: Optional[str] = None


class ChildObservationLogRevision(SQLModel, table=True):
    __tablename__ = "child_observation_log_revisions"
    __table_args__ = (
        UniqueConstraint("log_id", "revision_no", name="uq_child_observation_log_revision_no"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    log_id: int = Field(foreign_key="child_observation_logs.id", index=True)
    revision_no: int
    snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reason: Optional[str] = None
    created_by: Optional[str] = None
    created_by_name: str
    created_at: datetime = Field(default_factory=utc_now)
