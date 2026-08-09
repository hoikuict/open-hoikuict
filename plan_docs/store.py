from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from typing import Annotated, Mapping, Protocol

from fastapi import Depends
from sqlalchemy import func, update as sql_update
from sqlmodel import Session, select

from database import get_session
from time_utils import utc_now

from .contracts import DocumentStatus, DocumentType, normalize_status
from .db_models import (
    PlanDocumentAction,
    PlanDocumentHeadRow,
    PlanDocumentRow,
    PlanExecutionChangeRow,
    PlanRevisionRow,
)
from .models import (
    PlanDocument,
    PlanSchedule,
    ScheduleCell,
    ScheduleColumn,
    ScheduleRow,
    SectionBlock,
)
from .serializers import document_to_dict
from .services.review_notifications import (
    create_review_notifications,
    resolve_review_notifications,
)


class ConcurrentUpdateError(RuntimeError):
    pass


class InvalidStatusTransitionError(RuntimeError):
    pass


class ExecutionChangeError(RuntimeError):
    pass


class DocumentRepository(Protocol):
    def create(self, document: PlanDocument) -> PlanDocument: ...

    def get(self, document_id: int) -> PlanDocument | None: ...

    def list(
        self,
        *,
        nursery_ref: str | None = None,
        classroom_refs: tuple[str, ...] | None = None,
        document_type: DocumentType | None = None,
        status: DocumentStatus | None = None,
    ) -> list[PlanDocument]: ...


def _section_from_dict(payload: dict) -> SectionBlock:
    return SectionBlock(
        section_key=str(payload.get("section_key") or ""),
        title=str(payload.get("title") or ""),
        body=str(payload.get("body") or ""),
        source_refs=list(payload.get("source_refs") or []),
        evidence_tags=list(payload.get("evidence_tags") or []),
        needs_confirmation=bool(payload.get("needs_confirmation")),
        editor_note=payload.get("editor_note") or None,
    )


def _schedule_from_dict(payload: dict | None) -> PlanSchedule | None:
    if not payload:
        return None
    columns = [
        ScheduleColumn(key=str(item.get("key") or ""), title=str(item.get("title") or ""))
        for item in payload.get("columns") or []
    ]
    rows: list[ScheduleRow] = []
    for item in payload.get("rows") or []:
        cells = {
            str(key): ScheduleCell(
                body=str(value.get("body") or ""),
                source_refs=list(value.get("source_refs") or ["form.schedule"]),
                needs_confirmation=bool(value.get("needs_confirmation")),
                editor_note=value.get("editor_note") or None,
            )
            for key, value in (item.get("cells") or {}).items()
        }
        rows.append(
            ScheduleRow(
                row_key=str(item.get("row_key") or ""),
                label=str(item.get("label") or ""),
                order=int(item.get("order") or 0),
                start_time=item.get("start_time") or None,
                cells=cells,
            )
        )
    return PlanSchedule(layout=str(payload.get("layout") or ""), columns=columns, rows=rows)


def _document_from_row(row: PlanDocumentRow) -> PlanDocument:
    return PlanDocument(
        id=int(row.id or 0),
        document_type=DocumentType(row.document_type),
        title=row.title,
        status=normalize_status(row.status),
        nursery_ref=row.nursery_ref,
        classroom_ref=row.classroom_ref,
        actor_ref=row.actor_ref,
        owner_name=row.owner_name,
        sections=[_section_from_dict(item) for item in row.sections],
        confirmation_items=list(row.confirmation_items or []),
        school_year=row.school_year,
        target_month=row.target_month,
        target_week=row.target_week,
        week_start_date=row.week_start_date,
        target_date=row.target_date,
        period_start=row.period_start,
        period_end=row.period_end,
        record_cycle_key=row.record_cycle_key,
        setting_version_id=row.setting_version_id,
        age_class=row.age_class,
        child_id=row.child_id,
        child_ref=row.child_ref,
        child_name=row.child_name,
        parent_document_id=row.parent_document_id,
        related_document_ids=list(row.related_document_ids or []),
        schedule=_schedule_from_dict(row.schedule),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_from_document(document: PlanDocument) -> PlanDocumentRow:
    payload = document_to_dict(document)
    return PlanDocumentRow(
        document_type=document.document_type.value,
        status=document.status.value,
        title=document.title,
        nursery_ref=document.nursery_ref,
        classroom_ref=document.classroom_ref,
        actor_ref=document.actor_ref,
        owner_name=document.owner_name,
        school_year=document.school_year,
        target_month=document.target_month,
        target_week=document.target_week,
        week_start_date=document.week_start_date,
        target_date=document.target_date,
        period_start=document.period_start,
        period_end=document.period_end,
        record_cycle_key=document.record_cycle_key,
        setting_version_id=document.setting_version_id,
        age_class=document.age_class,
        child_id=document.child_id,
        child_ref=document.child_ref,
        child_name=document.child_name,
        parent_document_id=document.parent_document_id,
        related_document_ids=list(document.related_document_ids),
        sections=list(payload["sections"]),
        schedule=payload.get("schedule"),
        confirmation_items=list(document.confirmation_items),
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _apply_document_to_row(document: PlanDocument, row: PlanDocumentRow) -> None:
    payload = document_to_dict(document)
    row.title = document.title
    row.status = document.status.value
    row.actor_ref = document.actor_ref
    row.owner_name = document.owner_name
    row.parent_document_id = document.parent_document_id
    row.related_document_ids = list(document.related_document_ids)
    row.sections = list(payload["sections"])
    row.schedule = payload.get("schedule")
    row.confirmation_items = list(document.confirmation_items)
    row.updated_at = document.updated_at


def _snapshot_hash(snapshot: dict) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SqlModelDocumentRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, document: PlanDocument) -> PlanDocument:
        now = utc_now()
        document.created_at = now
        document.updated_at = now
        row = _row_from_document(document)
        self.session.add(row)
        self.session.flush()
        document.id = int(row.id or 0)
        head = PlanDocumentHeadRow(
            document_id=document.id,
            nursery_ref=document.nursery_ref,
            classroom_ref=document.classroom_ref,
            target_date=document.target_date if document.document_type == DocumentType.DAILY_PLAN else None,
        )
        self.session.add(head)
        self.session.flush()
        revision = self._create_revision(document, reason="created")
        head.current_revision_id = revision.id
        self.session.add(head)
        self.session.commit()
        self.session.refresh(row)
        return _document_from_row(row)

    def get(self, document_id: int) -> PlanDocument | None:
        row = self.session.get(PlanDocumentRow, document_id)
        if row is None:
            return None
        head = self._head(document_id)
        if head is None:
            head = self._bootstrap_head(row)
        if head is not None and head.deleted_at is not None:
            return None
        return _document_from_row(row)

    def get_by_public_id(self, public_id: str) -> PlanDocument | None:
        head = self.session.exec(
            select(PlanDocumentHeadRow).where(PlanDocumentHeadRow.public_id == public_id)
        ).first()
        if head is None:
            return None
        return self.get(head.document_id)

    def list(
        self,
        *,
        nursery_ref: str | None = None,
        classroom_refs: tuple[str, ...] | None = None,
        document_type: DocumentType | None = None,
        status: DocumentStatus | None = None,
    ) -> list[PlanDocument]:
        statement = select(PlanDocumentRow)
        if nursery_ref:
            statement = statement.where(PlanDocumentRow.nursery_ref == nursery_ref)
        if classroom_refs:
            statement = statement.where(PlanDocumentRow.classroom_ref.in_(classroom_refs))
        if document_type:
            statement = statement.where(PlanDocumentRow.document_type == document_type.value)
        if status:
            statement = statement.where(PlanDocumentRow.status == status.value)
        statement = statement.order_by(PlanDocumentRow.updated_at.desc(), PlanDocumentRow.id.desc())
        rows = self.session.exec(statement).all()
        deleted_ids = set(
            self.session.exec(
                select(PlanDocumentHeadRow.document_id).where(PlanDocumentHeadRow.deleted_at.is_not(None))
            ).all()
        )
        return [_document_from_row(row) for row in rows if row.id not in deleted_ids]

    def head(self, document_id: int) -> PlanDocumentHeadRow | None:
        return self._head(document_id)

    def lock_version(self, document_id: int) -> int:
        head = self._required_head(document_id)
        return head.lock_version

    def revisions(self, document_id: int) -> list[PlanRevisionRow]:
        return list(
            self.session.exec(
                select(PlanRevisionRow)
                .where(PlanRevisionRow.document_id == document_id)
                .order_by(PlanRevisionRow.revision_no.desc())
            ).all()
        )

    def update_document(
        self,
        document_id: int,
        *,
        title: str,
        owner_name: str,
        confirmation_items: list[str],
        section_updates: dict[str, dict[str, object]],
        schedule_form: Mapping[str, str] | None = None,
        expected_lock_version: int,
        actor_ref: str,
    ) -> PlanDocument | None:
        row = self.session.get(PlanDocumentRow, document_id)
        if row is None:
            return None
        self._claim_lock(document_id, expected_lock_version)
        document = _document_from_row(row)
        document.title = title
        document.owner_name = owner_name
        document.confirmation_items = confirmation_items
        for section in document.sections:
            item = section_updates.get(section.section_key)
            if not item:
                continue
            section.body = str(item.get("body") or "")
            section.needs_confirmation = bool(item.get("needs_confirmation"))
            section.editor_note = str(item.get("editor_note") or "").strip() or None
        if document.schedule and schedule_form is not None:
            for schedule_row in document.schedule.rows:
                label = schedule_form.get(f"rowlabel__{schedule_row.row_key}")
                if label is not None:
                    schedule_row.label = label.strip() or schedule_row.label
                start_time = schedule_form.get(f"rowtime__{schedule_row.row_key}")
                if start_time is not None:
                    schedule_row.start_time = start_time.strip() or None
                for column in document.schedule.columns:
                    value = schedule_form.get(f"cell__{schedule_row.row_key}__{column.key}")
                    if value is None:
                        continue
                    cell = schedule_row.cells.setdefault(column.key, ScheduleCell())
                    cell.body = value.strip()
                    if cell.needs_confirmation and cell.body:
                        cell.needs_confirmation = False
                        cell.editor_note = None
        document.updated_at = utc_now()
        _apply_document_to_row(document, row)
        self.session.add(row)
        revision = self._create_revision(document, reason="edited", actor_ref=actor_ref)
        head = self._required_head(document_id)
        head.current_revision_id = revision.id
        head.updated_at = document.updated_at
        self.session.add(head)
        self.session.commit()
        self.session.refresh(row)
        return _document_from_row(row)

    def update_status(
        self,
        document_id: int,
        status: DocumentStatus,
        *,
        expected_lock_version: int,
        actor_ref: str,
        actor_name: str = "職員",
        comment: str | None = None,
    ) -> PlanDocument | None:
        row = self.session.get(PlanDocumentRow, document_id)
        if row is None:
            return None
        current = normalize_status(row.status)
        self._validate_transition(current, status)
        if status == DocumentStatus.REJECTED and not (comment or "").strip():
            raise InvalidStatusTransitionError("差戻し理由を入力してください")
        self._claim_lock(document_id, expected_lock_version)
        document = _document_from_row(row)
        document.status = status
        document.updated_at = utc_now()
        row.status = status.value
        row.updated_at = document.updated_at
        self.session.add(row)
        head = self._required_head(document_id)
        previous_review_revision_id = head.review_revision_id
        if status == DocumentStatus.IN_REVIEW:
            revision = self._create_revision(document, reason="submitted", actor_ref=actor_ref)
            head.current_revision_id = revision.id
            head.review_revision_id = revision.id
            create_review_notifications(
                self.session,
                document=document,
                review_revision_id=int(revision.id or 0),
                requested_by_ref=actor_ref,
                requested_by_name=actor_name,
            )
        elif status == DocumentStatus.APPROVED:
            if head.review_revision_id is None:
                raise InvalidStatusTransitionError("レビュー対象版がありません")
            head.approved_revision_id = head.review_revision_id
        elif status == DocumentStatus.DRAFT:
            head.review_revision_id = None
        if status != DocumentStatus.IN_REVIEW:
            resolve_review_notifications(
                self.session,
                document_id=document_id,
                review_revision_id=previous_review_revision_id,
            )
        head.updated_at = document.updated_at
        self.session.add(head)
        self.session.add(
            PlanDocumentAction(
                document_id=document_id,
                document_type=row.document_type,
                action=status.value,
                comment=comment,
                actor_ref=actor_ref,
            )
        )
        self.session.commit()
        self.session.refresh(row)
        return _document_from_row(row)

    def list_execution_changes(self, document_id: int) -> list[PlanExecutionChangeRow]:
        return list(
            self.session.exec(
                select(PlanExecutionChangeRow)
                .where(PlanExecutionChangeRow.document_id == document_id)
                .order_by(PlanExecutionChangeRow.changed_at, PlanExecutionChangeRow.id)
            ).all()
        )

    def create_execution_change(
        self,
        document_id: int,
        *,
        affected_block_key: str | None,
        reason_code: str,
        reason_note: str | None,
        impact_level: str,
        after_snapshot: dict,
        changed_at: datetime,
        actor_ref: str,
        corrects_change_id: int | None = None,
    ) -> PlanExecutionChangeRow:
        document = self.get(document_id)
        if document is None or document.document_type != DocumentType.DAILY_PLAN:
            raise ExecutionChangeError("日案が見つかりません")
        if document.status not in {DocumentStatus.IN_REVIEW, DocumentStatus.APPROVED}:
            raise ExecutionChangeError("レビュー中または承認済みの日案だけ実施変更を登録できます")
        if reason_code not in {"weather", "child_state", "safety", "staffing", "facility", "other"}:
            raise ExecutionChangeError("変更理由が不正です")
        if reason_code == "other" and not (reason_note or "").strip():
            raise ExecutionChangeError("その他の理由を入力してください")
        if impact_level not in {"minor", "significant", "critical"}:
            raise ExecutionChangeError("重要度が不正です")
        head = self._required_head(document_id)
        base_revision_id = (
            head.approved_revision_id
            if document.status == DocumentStatus.APPROVED
            else head.review_revision_id
        )
        if base_revision_id is None:
            raise ExecutionChangeError("基準となる固定リビジョンがありません")
        if corrects_change_id is not None:
            corrected = self.session.get(PlanExecutionChangeRow, corrects_change_id)
            if corrected is None or corrected.document_id != document_id:
                raise ExecutionChangeError("訂正元の実施変更が見つかりません")
        before_snapshot = self._execution_before_snapshot(
            document_id,
            int(base_revision_id),
            affected_block_key,
        )
        change = PlanExecutionChangeRow(
            document_id=document_id,
            base_revision_id=int(base_revision_id),
            approval_state_at_change=document.status.value,
            affected_block_key=affected_block_key,
            reason_code=reason_code,
            reason_note=(reason_note or "").strip() or None,
            impact_level=impact_level,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            changed_at=changed_at,
            recorded_by=actor_ref,
            confirmation_status="not_required" if impact_level == "minor" else "pending",
            corrects_change_id=corrects_change_id,
        )
        self.session.add(change)
        self.session.commit()
        self.session.refresh(change)
        return change

    def confirm_execution_change(
        self,
        document_id: int,
        change_id: int,
        *,
        actor_ref: str,
        comment: str | None,
    ) -> PlanExecutionChangeRow:
        change = self.session.get(PlanExecutionChangeRow, change_id)
        if change is None or change.document_id != document_id:
            raise ExecutionChangeError("実施変更が見つかりません")
        if change.confirmation_status == "not_required":
            raise ExecutionChangeError("軽微な変更に事後確認は不要です")
        if change.confirmation_status == "confirmed":
            return change
        change.confirmation_status = "confirmed"
        change.confirmed_by = actor_ref
        change.confirmed_at = utc_now()
        change.confirmation_comment = (comment or "").strip() or None
        self.session.add(change)
        self.session.commit()
        self.session.refresh(change)
        return change

    def _head(self, document_id: int) -> PlanDocumentHeadRow | None:
        return self.session.exec(
            select(PlanDocumentHeadRow).where(PlanDocumentHeadRow.document_id == document_id)
        ).first()

    def _required_head(self, document_id: int) -> PlanDocumentHeadRow:
        head = self._head(document_id)
        if head is None:
            raise RuntimeError("文書ヘッドが見つかりません")
        return head

    def _bootstrap_head(self, row: PlanDocumentRow) -> PlanDocumentHeadRow:
        document = _document_from_row(row)
        head = PlanDocumentHeadRow(
            document_id=document.id,
            nursery_ref=document.nursery_ref,
            classroom_ref=document.classroom_ref,
            target_date=(
                document.target_date
                if document.document_type == DocumentType.DAILY_PLAN
                else None
            ),
        )
        self.session.add(head)
        self.session.flush()
        revision = self._create_revision(document, reason="migrated", actor_ref="system:migration")
        head.current_revision_id = revision.id
        if document.status == DocumentStatus.IN_REVIEW:
            head.review_revision_id = revision.id
        elif document.status == DocumentStatus.APPROVED:
            head.review_revision_id = revision.id
            head.approved_revision_id = revision.id
        self.session.add(head)
        self.session.commit()
        self.session.refresh(head)
        return head

    def _claim_lock(self, document_id: int, expected_lock_version: int) -> None:
        now = utc_now()
        result = self.session.execute(
            sql_update(PlanDocumentHeadRow)
            .where(
                PlanDocumentHeadRow.document_id == document_id,
                PlanDocumentHeadRow.lock_version == expected_lock_version,
            )
            .values(lock_version=expected_lock_version + 1, updated_at=now)
        )
        if result.rowcount != 1:
            self.session.rollback()
            raise ConcurrentUpdateError("他の職員が先に更新しました。画面を再読み込みしてください")
        self.session.expire_all()

    def _create_revision(
        self,
        document: PlanDocument,
        *,
        reason: str,
        actor_ref: str | None = None,
    ) -> PlanRevisionRow:
        latest = self.session.exec(
            select(func.max(PlanRevisionRow.revision_no)).where(
                PlanRevisionRow.document_id == document.id
            )
        ).one()
        revision_no = int(latest or 0) + 1
        snapshot = document_to_dict(document)
        revision = PlanRevisionRow(
            document_id=document.id,
            revision_no=revision_no,
            snapshot=snapshot,
            reason=reason,
            content_hash=_snapshot_hash(snapshot),
            created_by=actor_ref or document.actor_ref or "system",
        )
        self.session.add(revision)
        self.session.flush()
        return revision

    def _execution_before_snapshot(
        self,
        document_id: int,
        base_revision_id: int,
        affected_block_key: str | None,
    ) -> dict:
        previous = self.session.exec(
            select(PlanExecutionChangeRow)
            .where(
                PlanExecutionChangeRow.document_id == document_id,
                PlanExecutionChangeRow.affected_block_key == affected_block_key,
            )
            .order_by(PlanExecutionChangeRow.changed_at.desc(), PlanExecutionChangeRow.id.desc())
        ).first()
        if previous is not None:
            return dict(previous.after_snapshot)
        revision = self.session.get(PlanRevisionRow, base_revision_id)
        if revision is None:
            return {}
        if affected_block_key is None:
            return dict(revision.snapshot)
        schedule = revision.snapshot.get("schedule") or {}
        for row in schedule.get("rows") or []:
            if row.get("row_key") == affected_block_key:
                return dict(row)
        raise ExecutionChangeError("対象の活動ブロックが基準版にありません")

    @staticmethod
    def _validate_transition(current: DocumentStatus, target: DocumentStatus) -> None:
        allowed = {
            DocumentStatus.DRAFT: {DocumentStatus.IN_REVIEW, DocumentStatus.ARCHIVED},
            DocumentStatus.IN_REVIEW: {
                DocumentStatus.DRAFT,
                DocumentStatus.APPROVED,
                DocumentStatus.REJECTED,
            },
            DocumentStatus.REJECTED: {
                DocumentStatus.DRAFT,
                DocumentStatus.IN_REVIEW,
                DocumentStatus.ARCHIVED,
            },
            DocumentStatus.APPROVED: {DocumentStatus.ARCHIVED},
            DocumentStatus.ARCHIVED: set(),
        }
        if target == current:
            return
        if target not in allowed[current]:
            raise InvalidStatusTransitionError(
                f"{current.value} から {target.value} へは変更できません"
            )


def get_document_repository(
    session: Annotated[Session, Depends(get_session)],
) -> SqlModelDocumentRepository:
    return SqlModelDocumentRepository(session)


DocumentRepositoryDep = Annotated[SqlModelDocumentRepository, Depends(get_document_repository)]


class DocumentStore:
    """テスト専用の互換インメモリ実装。実運用ルートからは使用しない。"""

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
            documents = [item for item in documents if item.nursery_ref == nursery_ref]
        if classroom_refs:
            documents = [item for item in documents if item.classroom_ref in classroom_refs]
        if document_type:
            documents = [item for item in documents if item.document_type == document_type]
        if status:
            documents = [item for item in documents if item.status == status]
        return sorted(documents, key=lambda item: item.updated_at, reverse=True)

    def clear(self) -> None:
        with self._lock:
            self._documents.clear()
            self._next_id = 1


document_store = DocumentStore()
