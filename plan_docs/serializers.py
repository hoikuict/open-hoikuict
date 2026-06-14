from __future__ import annotations

from .models import PlanDocument, PlanSchedule, ScheduleCell, SectionBlock


def section_to_dict(section: SectionBlock) -> dict[str, object]:
    return {
        "section_key": section.section_key,
        "title": section.title,
        "body": section.body,
        "source_refs": section.source_refs,
        "evidence_tags": section.evidence_tags,
        "needs_confirmation": section.needs_confirmation,
        "editor_note": section.editor_note,
    }


def schedule_cell_to_dict(cell: ScheduleCell) -> dict[str, object]:
    payload: dict[str, object] = {
        "body": cell.body,
        "source_refs": cell.source_refs,
        "evidence_tags": cell.evidence_tags,
        "needs_confirmation": cell.needs_confirmation,
    }
    if cell.editor_note:
        payload["editor_note"] = cell.editor_note
    return payload


def schedule_to_dict(schedule: PlanSchedule) -> dict[str, object]:
    return {
        "layout": schedule.layout,
        "columns": [{"key": column.key, "title": column.title} for column in schedule.columns],
        "rows": [
            {
                "row_key": row.row_key,
                "label": row.label,
                "order": row.order,
                **({"start_time": row.start_time} if row.start_time else {}),
                "cells": {
                    column.key: schedule_cell_to_dict(row.cells[column.key])
                    for column in schedule.columns
                    if column.key in row.cells
                },
            }
            for row in sorted(schedule.rows, key=lambda item: item.order)
        ],
    }


def document_to_dict(document: PlanDocument) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": document.id,
        "document_type": document.document_type.value,
        "document_type_label": document.document_type_label,
        "status": document.status.value,
        "status_label": document.status_label,
        "title": document.title,
        "nursery_ref": document.nursery_ref,
        "classroom_ref": document.classroom_ref,
        "actor_ref": document.actor_ref,
        "owner_name": document.owner_name,
        "school_year": document.school_year,
        "target_month": document.target_month,
        "sections": [section_to_dict(section) for section in document.sections],
        "confirmation_items": document.confirmation_items,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }
    if document.target_week:
        payload["target_week"] = document.target_week
    if document.week_start_date:
        payload["week_start_date"] = document.week_start_date
    if document.target_date:
        payload["target_date"] = document.target_date
    if document.age_class:
        payload["age_class"] = document.age_class
    if document.child_ref:
        payload["child_ref"] = document.child_ref
    if document.child_name:
        payload["child_name"] = document.child_name
    if document.parent_document_id is not None:
        payload["parent_document_id"] = document.parent_document_id
    if document.related_document_ids:
        payload["related_document_ids"] = document.related_document_ids
    if document.schedule is not None:
        payload["schedule"] = schedule_to_dict(document.schedule)
    return payload


serialize_document = document_to_dict
serialize_schedule = schedule_to_dict
