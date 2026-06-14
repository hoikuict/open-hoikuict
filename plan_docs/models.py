from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .contracts import DOCUMENT_TYPE_LABELS, STATUS_LABELS, DocumentStatus, DocumentType, evidence_tags_for


@dataclass(slots=True)
class SectionBlock:
    section_key: str
    title: str
    body: str
    source_refs: list[str]
    evidence_tags: list[str]
    needs_confirmation: bool = False
    editor_note: str | None = None


@dataclass(slots=True)
class ScheduleColumn:
    key: str
    title: str


@dataclass(slots=True)
class ScheduleCell:
    body: str = ""
    source_refs: list[str] = field(default_factory=lambda: ["form.schedule"])
    needs_confirmation: bool = False
    editor_note: str | None = None

    @property
    def evidence_tags(self) -> list[str]:
        return evidence_tags_for(self.source_refs)


@dataclass(slots=True)
class ScheduleRow:
    row_key: str
    label: str
    order: int
    start_time: str | None = None
    cells: dict[str, ScheduleCell] = field(default_factory=dict)


@dataclass(slots=True)
class PlanSchedule:
    layout: str
    columns: list[ScheduleColumn]
    rows: list[ScheduleRow]


@dataclass(slots=True)
class PlanDocument:
    id: int
    document_type: DocumentType
    title: str
    status: DocumentStatus
    nursery_ref: str
    classroom_ref: str
    actor_ref: str | None
    owner_name: str
    sections: list[SectionBlock]
    confirmation_items: list[str] = field(default_factory=list)
    school_year: int | None = None
    target_month: str | None = None
    target_week: str | None = None
    week_start_date: str | None = None
    target_date: str | None = None
    age_class: str | None = None
    child_id: int | None = None
    child_ref: str | None = None
    child_name: str | None = None
    parent_document_id: int | None = None
    related_document_ids: list[int] = field(default_factory=list)
    schedule: PlanSchedule | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def document_type_label(self) -> str:
        return DOCUMENT_TYPE_LABELS.get(self.document_type, self.document_type.value)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status.value)

    @property
    def can_edit_body(self) -> bool:
        return self.status in {DocumentStatus.DRAFT, DocumentStatus.REJECTED}

    @property
    def nursery_label(self) -> str:
        return self.nursery_ref

    @property
    def classroom_label(self) -> str:
        return self.classroom_ref
