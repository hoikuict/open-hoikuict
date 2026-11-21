"""Shared access and transaction guards for meeting-note lifecycle operations."""
from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from models import (
    MeetingNote, RecordHighlight, HighlightSourceType, InstitutionalRecordLink,
    InstitutionalRecord, RecordLinkTargetType, EventSeriesMember,
    EventSeriesMemberTargetType, EventSeries,
)

LABELS = {"active": "通常", "archived": "アーカイブ済み", "trashed": "ごみ箱"}
TRANSITIONS = {"archive": ("active", "archived"), "restore": ("archived", "active"),
               "trash": ("archived", "trashed"), "untrash": ("trashed", "archived")}
ACTION_LABELS = {"archive": "アーカイブ", "restore": "通常に戻す", "trash": "ごみ箱へ移動", "untrash": "アーカイブ済みに戻す"}


def load_note(session: Session, note_id: int, principal, *, edit: bool = False) -> MeetingNote:
    note = session.get(MeetingNote, note_id, populate_existing=True)
    if note is None or (note.lifecycle_status == "trashed" and not principal.is_admin):
        raise HTTPException(404, "この議事録は表示できません。管理者に確認してください。")
    if edit and (not principal.can_edit or note.lifecycle_status != "active"):
        raise HTTPException(409 if principal.can_edit else 403, "この議事録は閲覧専用です。通常に戻してから編集してください。")
    return note


def lock_for_edit(session: Session, note_id: int, principal) -> MeetingNote:
    if not principal.can_edit:
        raise HTTPException(403, "編集権限がありません")
    # Serializes reference creation/marking changes against archive/trash. On
    # SQLite this holds the writer lock until the caller commits or rolls back.
    result = session.execute(update(MeetingNote).where(
        MeetingNote.id == note_id, MeetingNote.lifecycle_status == "active",
    ).values(lifecycle_version=MeetingNote.lifecycle_version).execution_options(synchronize_session=False))
    note = load_note(session, note_id, principal, edit=True)
    if result.rowcount != 1:
        raise HTTPException(409, "議事録の状態が変わりました。画面を開き直してください。")
    return note


def relations(session: Session, note_id: int, principal) -> list[dict]:
    """All source dependencies block trash; disclose only visible target names."""
    from institutional_record_service import record_visible_to

    target_id = str(note_id)
    result = []
    highlights = session.exec(select(RecordHighlight).where(
        RecordHighlight.source_type == HighlightSourceType.meeting_note,
        RecordHighlight.source_id == target_id,
    )).all()
    if highlights:
        result.append({"label": f"マーキング・コメント（{len(highlights)}件のマーキング）", "url": f"/meeting-notes/{note_id}#markings"})
    links = session.exec(select(InstitutionalRecordLink).where(
        InstitutionalRecordLink.target_type == RecordLinkTargetType.meeting_note,
        InstitutionalRecordLink.target_id == target_id,
    )).all()
    for link in links:
        record = session.get(InstitutionalRecord, link.record_id)
        visible = record is not None and record_visible_to(session, principal, record)
        result.append({"label": "経緯レコード・参照履歴：" + (record.title if visible else "閲覧範囲外の記録"),
                       "url": f"/records/{record.id}" if visible else None})
    members = session.exec(select(EventSeriesMember).where(
        EventSeriesMember.target_type == EventSeriesMemberTargetType.meeting_note,
        EventSeriesMember.target_id == target_id,
    )).all()
    for member in members:
        series = session.get(EventSeries, member.series_id)
        result.append({"label": f"行事シリーズ：{series.name if series else '関連履歴'} / {member.fiscal_year}年度",
                       "url": f"/event-series/{member.series_id}"})
    return result
