from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import case, or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_admin, require_can_edit
from database import get_session
from models import (
    Child,
    Classroom,
    Notice,
    NoticeAttachment,
    NoticePriority,
    NoticeStatus,
    NoticeTarget,
    NoticeTargetType,
    NoticeWorkflowAction,
)
from notice_content import (
    NoticeContentError,
    cleanup_notice_uploads,
    legacy_notice_body_html,
    normalize_image_size,
    notice_attachment_path,
    notice_plain_text,
    render_notice_body_html,
    sanitize_notice_html,
    store_notice_uploads,
)
from template_utils import create_templates
from time_utils import ensure_utc_from_local, utc_now

router = APIRouter(prefix="/notices", tags=["notices"])
templates = create_templates()
NOTICE_SORT_OPTIONS = (
    ("updated_desc", "更新日時（新しい順）"),
    ("updated_asc", "更新日時（古い順）"),
    ("created_desc", "作成日時（新しい順）"),
    ("priority_desc", "優先度（重要→通常）"),
    ("priority_asc", "優先度（通常→重要）"),
    ("status_published", "状態（公開中→下書き）"),
    ("status_draft", "状態（下書き→公開中）"),
    ("title_asc", "タイトル（昇順）"),
)


def _parse_optional_datetime(raw: str) -> Optional[datetime]:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return ensure_utc_from_local(datetime.fromisoformat(value))
    except ValueError:
        return None


def _target_id(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_publish_window(publish_start_at: str, publish_end_at: str) -> tuple[Optional[datetime], Optional[datetime]]:
    start_at = _parse_optional_datetime(publish_start_at)
    end_at = _parse_optional_datetime(publish_end_at)
    if start_at and end_at and start_at > end_at:
        raise HTTPException(status_code=400, detail="公開終了日時は公開開始日時以降にしてください。")
    return start_at, end_at


def _load_notice(session: Session, notice_id: int) -> Notice:
    notice = session.exec(
        select(Notice)
        .options(
            selectinload(Notice.targets),
            selectinload(Notice.reads),
            selectinload(Notice.attachments),
            selectinload(Notice.workflow_actions),
        )
        .where(Notice.id == notice_id)
    ).first()
    if not notice:
        raise HTTPException(status_code=404, detail="お知らせが見つかりません")
    return notice


def _target_label(notice: Notice, classrooms_by_id: dict[int, Classroom], children_by_id: dict[int, Child]) -> str:
    if not notice.targets:
        return "全保護者"

    labels: list[str] = []
    for target in notice.targets:
        if target.target_type == NoticeTargetType.all:
            labels.append("全保護者")
        elif target.target_type == NoticeTargetType.classroom:
            classroom_id = _target_id(target.target_value)
            classroom = classrooms_by_id.get(classroom_id) if classroom_id is not None else None
            labels.append(f"クラス: {classroom.name}" if classroom else "クラス指定")
        elif target.target_type == NoticeTargetType.child:
            child_id = _target_id(target.target_value)
            child = children_by_id.get(child_id) if child_id is not None else None
            labels.append(f"園児: {child.full_name}" if child else "園児指定")
    return " / ".join(labels)


def _upsert_targets(
    session: Session,
    notice: Notice,
    target_type: NoticeTargetType,
    target_classroom_id: Optional[str],
    target_child_id: Optional[str],
) -> None:
    for target in list(notice.targets):
        session.delete(target)
    session.flush()

    if target_type == NoticeTargetType.all:
        session.add(NoticeTarget(notice_id=notice.id, target_type=target_type))
        return

    if target_type == NoticeTargetType.classroom and (target_classroom_id or "").strip():
        try:
            classroom_id = int(target_classroom_id)
        except (TypeError, ValueError):
            classroom_id = None
        if classroom_id is None:
            session.add(NoticeTarget(notice_id=notice.id, target_type=NoticeTargetType.all))
            return
        session.add(
            NoticeTarget(
                notice_id=notice.id,
                target_type=target_type,
                target_value=str(classroom_id),
            )
        )
        return

    if target_type == NoticeTargetType.child and (target_child_id or "").strip():
        try:
            child_id = int(target_child_id)
        except (TypeError, ValueError):
            child_id = None
        if child_id is None:
            session.add(NoticeTarget(notice_id=notice.id, target_type=NoticeTargetType.all))
            return
        session.add(
            NoticeTarget(
                notice_id=notice.id,
                target_type=target_type,
                target_value=str(child_id),
            )
        )
        return

    session.add(NoticeTarget(notice_id=notice.id, target_type=NoticeTargetType.all))


def _load_reference_data(session: Session) -> tuple[list[Classroom], list[Child]]:
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
    children = session.exec(select(Child).order_by(Child.last_name_kana, Child.first_name_kana)).all()
    return classrooms, children


def _editor_body_html(notice: Notice | None) -> str:
    if notice is None:
        return ""
    return sanitize_notice_html(notice.body_html) if notice.body_html else legacy_notice_body_html(notice.body)


def _add_stored_attachments(
    session: Session,
    notice: Notice,
    stored_attachments,
    *,
    image_size: str,
    starting_order: int = 0,
) -> None:
    for offset, stored in enumerate(stored_attachments):
        session.add(
            NoticeAttachment(
                notice_id=notice.id,
                original_filename=stored.original_filename,
                storage_path=stored.storage_path,
                content_type=stored.content_type,
                file_size=stored.file_size,
                is_image=stored.is_image,
                display_size=image_size if stored.is_image else "medium",
                display_order=starting_order + offset,
            )
        )


def _record_workflow_action(
    session: Session,
    notice: Notice,
    *,
    action: str,
    current_user,
    comment: str | None = None,
) -> None:
    session.add(
        NoticeWorkflowAction(
            notice_id=notice.id,
            action=action,
            actor_ref=str(current_user.user_id) if current_user.user_id else None,
            actor_name=current_user.name,
            comment=(comment or "").strip() or None,
        )
    )


def _require_notice_status(notice: Notice, expected: NoticeStatus, message: str) -> None:
    if notice.status != expected:
        raise HTTPException(status_code=409, detail=message)


@router.get("/", response_class=HTMLResponse)
def notice_list(
    request: Request,
    q: str = Query(default="", max_length=100),
    status_filter: str = Query(default="all", alias="status"),
    priority_filter: str = Query(default="all", alias="priority"),
    sort: str = Query(default="updated_desc"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    current_query = q.strip()
    current_status = status_filter if status_filter in {"all", *(item.value for item in NoticeStatus)} else "all"
    current_priority = (
        priority_filter if priority_filter in {"all", *(item.value for item in NoticePriority)} else "all"
    )
    valid_sort_values = {value for value, _label in NOTICE_SORT_OPTIONS}
    current_sort = sort if sort in valid_sort_values else "updated_desc"

    classrooms, children = _load_reference_data(session)
    classrooms_by_id = {classroom.id: classroom for classroom in classrooms}
    children_by_id = {child.id: child for child in children}
    statement = (
        select(Notice)
        .options(selectinload(Notice.targets), selectinload(Notice.reads))
    )
    if current_query:
        search_filters = [
            Notice.title.contains(current_query, autoescape=True),
            Notice.body.contains(current_query, autoescape=True),
            Notice.created_by.contains(current_query, autoescape=True),
        ]
        if current_query.isdigit():
            search_filters.append(Notice.id == int(current_query))
        statement = statement.where(or_(*search_filters))
    if current_status != "all":
        statement = statement.where(Notice.status == NoticeStatus(current_status))
    if current_priority != "all":
        statement = statement.where(Notice.priority == NoticePriority(current_priority))

    priority_rank = case((Notice.priority == NoticePriority.high, 0), else_=1)
    status_published_rank = case((Notice.status == NoticeStatus.published, 0), else_=1)
    status_draft_rank = case((Notice.status == NoticeStatus.draft, 0), else_=1)
    order_by = {
        "updated_desc": (Notice.updated_at.desc(), Notice.created_at.desc()),
        "updated_asc": (Notice.updated_at.asc(), Notice.created_at.asc()),
        "created_desc": (Notice.created_at.desc(), Notice.id.desc()),
        "priority_desc": (priority_rank.asc(), Notice.updated_at.desc()),
        "priority_asc": (priority_rank.desc(), Notice.updated_at.desc()),
        "status_published": (status_published_rank.asc(), Notice.updated_at.desc()),
        "status_draft": (status_draft_rank.asc(), Notice.updated_at.desc()),
        "title_asc": (Notice.title.asc(), Notice.updated_at.desc()),
    }[current_sort]
    notices = session.exec(statement.order_by(*order_by)).all()
    target_labels = {notice.id: _target_label(notice, classrooms_by_id, children_by_id) for notice in notices}

    return templates.TemplateResponse(
        request,
        "notices/list.html",
        {
            "request": request,
            "notices": notices,
            "target_labels": target_labels,
            "current_user": current_user,
            "current_query": current_query,
            "current_status": current_status,
            "current_priority": current_priority,
            "current_sort": current_sort,
            "status_options": list(NoticeStatus),
            "priority_options": list(NoticePriority),
            "sort_options": NOTICE_SORT_OPTIONS,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_notice_form(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    classrooms, children = _load_reference_data(session)
    return templates.TemplateResponse(
        request,
        "notices/form.html",
        {
            "request": request,
            "notice": None,
            "classrooms": classrooms,
            "children": children,
            "action_url": "/notices/",
            "submit_label": "下書きを作成",
            "current_user": current_user,
            "status_options": list(NoticeStatus),
            "priority_options": list(NoticePriority),
            "selected_target_type": NoticeTargetType.all.value,
            "selected_target_classroom_id": "",
            "selected_target_child_id": "",
            "editor_body_html": "",
        },
    )


@router.post("/")
def create_notice(
    title: str = Form(...),
    body: str = Form(""),
    body_html: str = Form(""),
    priority: str = Form("normal"),
    status: str = Form("draft"),
    publish_start_at: str = Form(""),
    publish_end_at: str = Form(""),
    target_type: str = Form("all"),
    target_classroom_id: str = Form(""),
    target_child_id: str = Form(""),
    new_image_size: str = Form("medium"),
    attachments: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)

    try:
        normalized_priority = NoticePriority(priority)
    except ValueError:
        normalized_priority = NoticePriority.normal
    _ = status
    try:
        normalized_target_type = NoticeTargetType(target_type)
    except ValueError:
        normalized_target_type = NoticeTargetType.all
    publish_start, publish_end = _parse_publish_window(publish_start_at, publish_end_at)

    sanitized_body_html = sanitize_notice_html(body_html)
    normalized_body = notice_plain_text(sanitized_body_html) or body.strip()
    try:
        stored_attachments = store_notice_uploads(attachments)
    except NoticeContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not normalized_body and not stored_attachments:
        raise HTTPException(status_code=400, detail="本文または添付ファイルを入力してください。")

    notice = Notice(
        title=title.strip(),
        body=normalized_body,
        body_html=sanitized_body_html or None,
        priority=normalized_priority,
        status=NoticeStatus.draft,
        publish_start_at=publish_start,
        publish_end_at=publish_end,
        created_by=current_user.name,
    )
    session.add(notice)
    try:
        session.flush()
        _upsert_targets(session, notice, normalized_target_type, target_classroom_id, target_child_id)
        _add_stored_attachments(
            session,
            notice,
            stored_attachments,
            image_size=normalize_image_size(new_image_size),
        )
        session.commit()
    except Exception:
        session.rollback()
        cleanup_notice_uploads(item.storage_path for item in stored_attachments)
        raise
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.get("/{notice_id}/preview", response_class=HTMLResponse)
def preview_notice(
    request: Request,
    notice_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    notice = _load_notice(session, notice_id)
    return templates.TemplateResponse(
        request,
        "notices/preview.html",
        {
            "request": request,
            "notice": notice,
            "notice_body_html": render_notice_body_html(notice.body, notice.body_html),
            "workflow_actions": sorted(
                notice.workflow_actions,
                key=lambda item: (item.created_at, item.id or 0),
                reverse=True,
            ),
            "current_user": current_user,
        },
    )


@router.get("/{notice_id}/edit", response_class=HTMLResponse)
def edit_notice_form(
    request: Request,
    notice_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.draft,
        "承認待ちまたは公開中のお知らせは編集できません。確認画面から状態を変更してください。",
    )
    classrooms, children = _load_reference_data(session)

    selected_target_type = NoticeTargetType.all.value
    selected_target_classroom_id = ""
    selected_target_child_id = ""
    if notice.targets:
        target = notice.targets[0]
        selected_target_type = target.target_type.value
        if target.target_type == NoticeTargetType.classroom:
            selected_target_classroom_id = target.target_value or ""
        elif target.target_type == NoticeTargetType.child:
            selected_target_child_id = target.target_value or ""

    return templates.TemplateResponse(
        request,
        "notices/form.html",
        {
            "request": request,
            "notice": notice,
            "classrooms": classrooms,
            "children": children,
            "action_url": f"/notices/{notice_id}/edit",
            "submit_label": "下書きを保存",
            "current_user": current_user,
            "status_options": list(NoticeStatus),
            "priority_options": list(NoticePriority),
            "selected_target_type": selected_target_type,
            "selected_target_classroom_id": selected_target_classroom_id,
            "selected_target_child_id": selected_target_child_id,
            "editor_body_html": _editor_body_html(notice),
        },
    )


@router.post("/{notice_id}/edit")
def update_notice(
    notice_id: int,
    title: str = Form(...),
    body: str = Form(""),
    body_html: str = Form(""),
    priority: str = Form("normal"),
    status: str = Form("draft"),
    publish_start_at: str = Form(""),
    publish_end_at: str = Form(""),
    target_type: str = Form("all"),
    target_classroom_id: str = Form(""),
    target_child_id: str = Form(""),
    new_image_size: str = Form("medium"),
    attachment_size_ids: list[int] = Form(default=[]),
    attachment_sizes: list[str] = Form(default=[]),
    remove_attachment_ids: list[int] = Form(default=[]),
    attachments: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.draft,
        "承認待ちまたは公開中のお知らせは編集できません。確認画面から状態を変更してください。",
    )

    try:
        normalized_priority = NoticePriority(priority)
    except ValueError:
        normalized_priority = NoticePriority.normal
    _ = status
    try:
        normalized_target_type = NoticeTargetType(target_type)
    except ValueError:
        normalized_target_type = NoticeTargetType.all
    publish_start, publish_end = _parse_publish_window(publish_start_at, publish_end_at)

    attachment_by_id = {
        attachment.id: attachment
        for attachment in notice.attachments
        if attachment.id is not None
    }
    removable_ids = {
        attachment_id
        for attachment_id in remove_attachment_ids
        if attachment_id in attachment_by_id
    }
    kept_count = len(attachment_by_id) - len(removable_ids)
    try:
        stored_attachments = store_notice_uploads(
            attachments,
            existing_count=kept_count,
        )
    except NoticeContentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sanitized_body_html = sanitize_notice_html(body_html)
    normalized_body = notice_plain_text(sanitized_body_html) or body.strip()
    if not normalized_body and kept_count == 0 and not stored_attachments:
        cleanup_notice_uploads(item.storage_path for item in stored_attachments)
        raise HTTPException(status_code=400, detail="本文または添付ファイルを入力してください。")

    notice.title = title.strip()
    notice.body = normalized_body
    notice.body_html = sanitized_body_html or None
    notice.priority = normalized_priority
    notice.status = NoticeStatus.draft
    notice.publish_start_at = publish_start
    notice.publish_end_at = publish_end
    notice.updated_at = utc_now()
    session.add(notice)
    removed_storage_paths: list[str] = []
    try:
        for attachment_id, size in zip(attachment_size_ids, attachment_sizes):
            attachment = attachment_by_id.get(attachment_id)
            if attachment is not None and attachment.is_image:
                attachment.display_size = normalize_image_size(size)
                session.add(attachment)
        for attachment_id in removable_ids:
            attachment = attachment_by_id[attachment_id]
            removed_storage_paths.append(attachment.storage_path)
            session.delete(attachment)
        _upsert_targets(session, notice, normalized_target_type, target_classroom_id, target_child_id)
        next_order = max(
            (
                attachment.display_order
                for attachment_id, attachment in attachment_by_id.items()
                if attachment_id not in removable_ids
            ),
            default=-1,
        ) + 1
        _add_stored_attachments(
            session,
            notice,
            stored_attachments,
            image_size=normalize_image_size(new_image_size),
            starting_order=next_order,
        )
        session.commit()
    except Exception:
        session.rollback()
        cleanup_notice_uploads(item.storage_path for item in stored_attachments)
        raise
    cleanup_notice_uploads(removed_storage_paths)
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.post("/{notice_id}/submit")
def submit_notice_for_approval(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(notice, NoticeStatus.draft, "下書きだけ承認申請できます。")
    if not notice.title.strip() or (not notice.body.strip() and not notice.attachments):
        raise HTTPException(status_code=400, detail="タイトルと本文または添付を確認してください。")
    notice.status = NoticeStatus.pending_approval
    notice.updated_at = utc_now()
    session.add(notice)
    _record_workflow_action(
        session,
        notice,
        action="submitted",
        current_user=current_user,
    )
    session.commit()
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.post("/{notice_id}/approve")
def approve_notice(
    notice_id: int,
    comment: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.pending_approval,
        "承認待ちのお知らせだけ承認できます。",
    )
    notice.status = NoticeStatus.published
    notice.updated_at = utc_now()
    session.add(notice)
    _record_workflow_action(
        session,
        notice,
        action="approved",
        current_user=current_user,
        comment=comment,
    )
    session.commit()
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.post("/{notice_id}/reject")
def reject_notice(
    notice_id: int,
    reason: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise HTTPException(status_code=400, detail="差戻し理由を入力してください。")
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.pending_approval,
        "承認待ちのお知らせだけ差戻しできます。",
    )
    notice.status = NoticeStatus.draft
    notice.updated_at = utc_now()
    session.add(notice)
    _record_workflow_action(
        session,
        notice,
        action="rejected",
        current_user=current_user,
        comment=normalized_reason,
    )
    session.commit()
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.post("/{notice_id}/cancel-submission")
def cancel_notice_submission(
    notice_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.pending_approval,
        "承認待ちのお知らせだけ申請を取り消せます。",
    )
    notice.status = NoticeStatus.draft
    notice.updated_at = utc_now()
    session.add(notice)
    _record_workflow_action(
        session,
        notice,
        action="cancelled",
        current_user=current_user,
    )
    session.commit()
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.post("/{notice_id}/unpublish")
def unpublish_notice(
    notice_id: int,
    reason: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    notice = _load_notice(session, notice_id)
    _require_notice_status(
        notice,
        NoticeStatus.published,
        "公開中のお知らせだけ下書きに戻せます。",
    )
    notice.status = NoticeStatus.draft
    notice.updated_at = utc_now()
    session.add(notice)
    _record_workflow_action(
        session,
        notice,
        action="unpublished",
        current_user=current_user,
        comment=reason,
    )
    session.commit()
    return RedirectResponse(url=f"/notices/{notice.id}/preview", status_code=303)


@router.get("/attachments/{attachment_id}")
def notice_attachment(
    attachment_id: int,
    download: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    _ = current_user
    attachment = session.get(NoticeAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="添付ファイルが見つかりません。")
    path = notice_attachment_path(attachment.storage_path)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="添付ファイルの保存先が見つかりません。")
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
        content_disposition_type="attachment" if download else "inline",
    )
