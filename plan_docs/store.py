from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Mapping

from .contracts import DocumentStatus, DocumentType
from .models import PlanDocument, ScheduleCell


class DocumentStore:
    def __init__(self) -> None:
        self._documents: dict[int, PlanDocument] = {}
        self._next_id = 1
        self._lock = Lock()

    def create(self, document: PlanDocument) -> PlanDocument:
        with self._lock:
            document.id = self._next_id
            self._next_id += 1
            now = datetime.now(UTC)
            document.created_at = now
            document.updated_at = now
            self._documents[document.id] = document
            return document

    def get(self, document_id: int) -> PlanDocument | None:
        return self._documents.get(document_id)

    def list(
        self,
        *,
        nursery_ref: str | None = None,
        classroom_refs: tuple[str, ...] | None = None,
        document_type: DocumentType | None = None,
        status: DocumentStatus | None = None,
    ) -> list[PlanDocument]:
        documents = list(self._documents.values())
        if nursery_ref:
            documents = [document for document in documents if document.nursery_ref == nursery_ref]
        if classroom_refs:
            documents = [document for document in documents if document.classroom_ref in classroom_refs]
        if document_type:
            documents = [document for document in documents if document.document_type == document_type]
        if status:
            documents = [document for document in documents if document.status == status]
        return sorted(documents, key=lambda document: document.updated_at, reverse=True)

    def update_status(self, document_id: int, status: DocumentStatus) -> PlanDocument | None:
        document = self.get(document_id)
        if document is None:
            return None
        document.status = status
        document.updated_at = datetime.now(UTC)
        return document

    def update_document(
        self,
        document_id: int,
        *,
        title: str,
        owner_name: str,
        confirmation_items: list[str],
        section_updates: dict[str, dict[str, object]],
        schedule_form: Mapping[str, str] | None = None,
    ) -> PlanDocument | None:
        document = self.get(document_id)
        if document is None:
            return None
        document.title = title
        document.owner_name = owner_name
        document.confirmation_items = confirmation_items
        for section in document.sections:
            update = section_updates.get(section.section_key)
            if not update:
                continue
            section.body = str(update.get("body") or "")
            section.needs_confirmation = bool(update.get("needs_confirmation"))
            editor_note = str(update.get("editor_note") or "").strip()
            section.editor_note = editor_note or None
        if document.schedule and schedule_form is not None:
            for row in document.schedule.rows:
                new_label = schedule_form.get(f"rowlabel__{row.row_key}")
                if new_label is not None:
                    row.label = new_label.strip() or row.label
                new_time = schedule_form.get(f"rowtime__{row.row_key}")
                if new_time is not None:
                    row.start_time = new_time.strip() or None
                for column in document.schedule.columns:
                    value = schedule_form.get(f"cell__{row.row_key}__{column.key}")
                    if value is None:
                        continue
                    cell = row.cells.setdefault(column.key, ScheduleCell())
                    cell.body = value.strip()
                    if cell.needs_confirmation and cell.body:
                        cell.needs_confirmation = False
                        cell.editor_note = None
        document.updated_at = datetime.now(UTC)
        return document

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()
            self._next_id = 1


document_store = DocumentStore()
