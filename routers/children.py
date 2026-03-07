from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, Query, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from models import Child, ChildStatus, Guardian, CHILD_FIELDS
from database import engine
from auth import get_mock_current_user, require_can_edit

router = APIRouter(prefix="/children", tags=["children"])
templates = Jinja2Templates(directory="templates")


def get_session():
    with Session(engine) as session:
        yield session


@router.get("/", response_class=HTMLResponse)
def list_children(
    request: Request,
    status: Optional[str] = Query(default="enrolled"),
    fields: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    """名簿一覧ページ"""
    stmt = select(Child).options(selectinload(Child.guardians), selectinload(Child.older_sibling))
    if status and status != "all":
        stmt = stmt.where(Child.status == status)
    stmt = stmt.order_by(Child.last_name_kana)
    children = session.exec(stmt).all()

    # 選択フィールドが未指定の場合はデフォルトを使用
    if not fields:
        fields = [f["key"] for f in CHILD_FIELDS if f["default"]]

    return templates.TemplateResponse("children/list.html", {
        "request": request,
        "children": children,
        "all_fields": CHILD_FIELDS,
        "selected_fields": fields,
        "current_status": status,
        "total": len(children),
        "current_user": current_user,
    })


@router.get("/table", response_class=HTMLResponse)
def children_table(
    request: Request,
    status: Optional[str] = Query(default="enrolled"),
    fields: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    """HTMX用: テーブル部分だけ返す"""
    stmt = select(Child).options(selectinload(Child.guardians), selectinload(Child.older_sibling))
    if status and status != "all":
        stmt = stmt.where(Child.status == status)
    stmt = stmt.order_by(Child.last_name_kana)
    children = session.exec(stmt).all()

    if not fields:
        fields = [f["key"] for f in CHILD_FIELDS if f["default"]]

    field_labels = {f["key"]: f["label"] for f in CHILD_FIELDS}

    return templates.TemplateResponse("children/_table.html", {
        "request": request,
        "children": children,
        "selected_fields": fields,
        "field_labels": field_labels,
        "total": len(children),
        "current_user": current_user,
    })


def _parse_date(s: Optional[str]) -> Optional[date]:
    """文字列をdateに変換"""
    if not s or not s.strip():
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


@router.get("/new", response_class=HTMLResponse)
def new_child_form(
    request: Request,
    sibling_id: Optional[int] = Query(None, description="兄姉のID（情報を引き継ぐ）"),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    """新規園児登録フォーム（兄姉から引き継ぐ場合はsibling_idを指定）"""
    require_can_edit(current_user)
    inherit_from = None
    if sibling_id:
        stmt = select(Child).options(selectinload(Child.guardians), selectinload(Child.older_sibling)).where(Child.id == sibling_id)
        inherit_from = session.exec(stmt).first()

    # 兄姉選択用の園児一覧（在園・卒園・退園すべて）
    all_children = session.exec(select(Child).order_by(Child.last_name_kana)).all()

    if inherit_from:
        guardians = sorted(inherit_from.guardians, key=lambda g: g.order)
        g1 = guardians[0] if len(guardians) > 0 else None
        g2 = guardians[1] if len(guardians) > 1 else None
        return templates.TemplateResponse("children/form.html", {
            "request": request,
            "child": None,
            "guardian1": g1,
            "guardian2": g2,
            "action_url": "/children/",
            "submit_label": "登録する",
            "page_title": "園児を追加（兄弟）",
            "inherit_from": inherit_from,
            "older_sibling_id": sibling_id,
            "all_children": all_children,
            "current_user": current_user,
        })
    return templates.TemplateResponse("children/form.html", {
        "request": request,
        "child": None,
        "guardian1": None,
        "guardian2": None,
        "action_url": "/children/",
        "submit_label": "登録する",
        "page_title": "園児を追加",
        "inherit_from": None,
        "older_sibling_id": None,
        "all_children": all_children,
        "current_user": current_user,
    })


def _parse_guardian(
    ln: str, fn: str, lnk: str, fnk: str, rel: str, ph: str,
    wp: Optional[str], wpa: Optional[str], wph: Optional[str],
) -> Optional[Guardian]:
    """保護者フォームからGuardianを作成（姓名があれば有効）"""
    if not (ln and fn) or (not ln.strip() and not fn.strip()):
        return None
    return Guardian(
        last_name=ln.strip(),
        first_name=fn.strip(),
        last_name_kana=(lnk or "").strip() or None,
        first_name_kana=(fnk or "").strip() or None,
        relationship=(rel or "父").strip(),
        phone=(ph or "").strip() or None,
        workplace=(wp or "").strip() or None,
        workplace_address=(wpa or "").strip() or None,
        workplace_phone=(wph or "").strip() or None,
    )


def _form_data_for_create(
    last_name: str, first_name: str, last_name_kana: str, first_name_kana: str,
    birth_date: str, enrollment_date: str, withdrawal_date: str,
    status: str, home_address: str, home_phone: str, older_sibling_id: str,
    allergy: str, medical_notes: str,
    g1_last_name: str, g1_first_name: str, g1_last_name_kana: str, g1_first_name_kana: str,
    g1_relationship: str, g1_phone: str, g1_workplace: str, g1_workplace_address: str, g1_workplace_phone: str,
    g2_last_name: str, g2_first_name: str, g2_last_name_kana: str, g2_first_name_kana: str,
    g2_relationship: str, g2_phone: str, g2_workplace: str, g2_workplace_address: str, g2_workplace_phone: str,
) -> dict:
    """バリデーションエラー時のフォーム再表示用データ"""
    guardians = []
    if g1_last_name or g1_first_name:
        guardians.append({"last_name": g1_last_name, "first_name": g1_first_name, "last_name_kana": g1_last_name_kana,
                         "first_name_kana": g1_first_name_kana, "relationship": g1_relationship, "phone": g1_phone,
                         "workplace": g1_workplace, "workplace_address": g1_workplace_address, "workplace_phone": g1_workplace_phone})
    if g2_last_name or g2_first_name:
        guardians.append({"last_name": g2_last_name, "first_name": g2_first_name, "last_name_kana": g2_last_name_kana,
                         "first_name_kana": g2_first_name_kana, "relationship": g2_relationship, "phone": g2_phone,
                         "workplace": g2_workplace, "workplace_address": g2_workplace_address, "workplace_phone": g2_workplace_phone})
    return {
        "last_name": last_name, "first_name": first_name,
        "last_name_kana": last_name_kana, "first_name_kana": first_name_kana,
        "birth_date": birth_date, "enrollment_date": enrollment_date, "withdrawal_date": withdrawal_date or "",
        "status": status, "home_address": home_address or "", "home_phone": home_phone or "",
        "older_sibling_id": older_sibling_id, "allergy": allergy, "medical_notes": medical_notes,
        "guardians": guardians,
    }


@router.post("/")
def create_child(
    request: Request,
    current_user=Depends(get_mock_current_user),
    last_name: str = Form(...),
    first_name: str = Form(...),
    last_name_kana: str = Form(...),
    first_name_kana: str = Form(...),
    birth_date: Optional[str] = Form(None),
    enrollment_date: Optional[str] = Form(None),
    withdrawal_date: Optional[str] = Form(None),
    status: str = Form("enrolled"),
    home_address: Optional[str] = Form(None),
    home_phone: Optional[str] = Form(None),
    older_sibling_id: Optional[str] = Form(None),
    allergy: str = Form(""),
    medical_notes: str = Form(""),
    # 保護者1
    g1_last_name: str = Form(""),
    g1_first_name: str = Form(""),
    g1_last_name_kana: str = Form(""),
    g1_first_name_kana: str = Form(""),
    g1_relationship: str = Form("父"),
    g1_phone: str = Form(""),
    g1_workplace: str = Form(""),
    g1_workplace_address: str = Form(""),
    g1_workplace_phone: str = Form(""),
    # 保護者2
    g2_last_name: str = Form(""),
    g2_first_name: str = Form(""),
    g2_last_name_kana: str = Form(""),
    g2_first_name_kana: str = Form(""),
    g2_relationship: str = Form("母"),
    g2_phone: str = Form(""),
    g2_workplace: str = Form(""),
    g2_workplace_address: str = Form(""),
    g2_workplace_phone: str = Form(""),
    session: Session = Depends(get_session),
):
    """園児を新規登録"""
    require_can_edit(current_user)
    bd = _parse_date(birth_date)
    ed = _parse_date(enrollment_date)
    wd = _parse_date(withdrawal_date)
    if not bd or not ed:
        form_data = _form_data_for_create(
            last_name, first_name, last_name_kana, first_name_kana,
            birth_date, enrollment_date, withdrawal_date or "",
            status, home_address or "", home_phone or "", older_sibling_id or "",
            allergy, medical_notes,
            g1_last_name, g1_first_name, g1_last_name_kana, g1_first_name_kana,
            g1_relationship, g1_phone, g1_workplace, g1_workplace_address, g1_workplace_phone,
            g2_last_name, g2_first_name, g2_last_name_kana, g2_first_name_kana,
            g2_relationship, g2_phone, g2_workplace, g2_workplace_address, g2_workplace_phone,
        )
        all_children = []
        with Session(engine) as sess:
            all_children = sess.exec(select(Child).order_by(Child.last_name_kana)).all()
        return templates.TemplateResponse("children/form.html", {
            "request": request,
            "child": None,
            "guardian1": {"last_name": g1_last_name, "first_name": g1_first_name, "last_name_kana": g1_last_name_kana,
                          "first_name_kana": g1_first_name_kana, "relationship": g1_relationship, "phone": g1_phone,
                          "workplace": g1_workplace, "workplace_address": g1_workplace_address, "workplace_phone": g1_workplace_phone} if (g1_last_name or g1_first_name) else None,
            "guardian2": {"last_name": g2_last_name, "first_name": g2_first_name, "last_name_kana": g2_last_name_kana,
                          "first_name_kana": g2_first_name_kana, "relationship": g2_relationship, "phone": g2_phone,
                          "workplace": g2_workplace, "workplace_address": g2_workplace_address, "workplace_phone": g2_workplace_phone} if (g2_last_name or g2_first_name) else None,
            "action_url": "/children/",
            "submit_label": "登録する",
            "page_title": "園児を追加",
            "inherit_from": None,
            "older_sibling_id": int(older_sibling_id) if older_sibling_id and str(older_sibling_id).strip().isdigit() else None,
            "all_children": all_children,
            "form_error": "生年月日と入園日は必須です。正しい日付を入力してください。",
            "form_data": form_data,
            "current_user": current_user,
        }, status_code=400)
    try:
        st = ChildStatus(status)
    except ValueError:
        st = ChildStatus.enrolled

    allergies = [a.strip() for a in allergy.replace("、", ",").split(",") if a.strip()]
    extra_data = {"allergy": allergies, "medical_notes": medical_notes or ""}

    child = Child(
        last_name=last_name.strip(),
        first_name=first_name.strip(),
        last_name_kana=last_name_kana.strip(),
        first_name_kana=first_name_kana.strip(),
        birth_date=bd,
        enrollment_date=ed,
        withdrawal_date=wd,
        status=st,
        home_address=(home_address or "").strip() or None,
        home_phone=(home_phone or "").strip() or None,
        older_sibling_id=int(older_sibling_id) if older_sibling_id and str(older_sibling_id).strip().isdigit() else None,
        extra_data=extra_data,
    )
    session.add(child)
    session.flush()

    g1 = _parse_guardian(g1_last_name, g1_first_name, g1_last_name_kana, g1_first_name_kana,
                         g1_relationship, g1_phone, g1_workplace, g1_workplace_address, g1_workplace_phone)
    if g1:
        g1.child_id = child.id
        g1.order = 1
        session.add(g1)
    g2 = _parse_guardian(g2_last_name, g2_first_name, g2_last_name_kana, g2_first_name_kana,
                         g2_relationship, g2_phone, g2_workplace, g2_workplace_address, g2_workplace_phone)
    if g2:
        g2.child_id = child.id
        g2.order = 2
        session.add(g2)

    session.commit()
    return RedirectResponse(url="/children/", status_code=303)


@router.get("/{child_id}/edit", response_class=HTMLResponse)
def edit_child_form(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    """園児編集フォーム"""
    require_can_edit(current_user)
    stmt = select(Child).options(selectinload(Child.guardians), selectinload(Child.older_sibling)).where(Child.id == child_id)
    child = session.exec(stmt).first()
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    guardians = sorted(child.guardians, key=lambda g: g.order)
    g1 = guardians[0] if len(guardians) > 0 else None
    g2 = guardians[1] if len(guardians) > 1 else None
    return templates.TemplateResponse("children/form.html", {
        "request": request,
        "child": child,
        "guardian1": g1,
        "guardian2": g2,
        "action_url": f"/children/{child_id}/edit",
        "submit_label": "更新する",
        "page_title": f"{child.full_name} を編集",
        "current_user": current_user,
    })


@router.post("/{child_id}/edit")
def update_child(
    request: Request,
    child_id: int,
    current_user=Depends(get_mock_current_user),
    last_name: str = Form(...),
    first_name: str = Form(...),
    last_name_kana: str = Form(...),
    first_name_kana: str = Form(...),
    birth_date: Optional[str] = Form(None),
    enrollment_date: Optional[str] = Form(None),
    withdrawal_date: Optional[str] = Form(None),
    status: str = Form("enrolled"),
    home_address: Optional[str] = Form(None),
    home_phone: Optional[str] = Form(None),
    allergy: str = Form(""),
    medical_notes: str = Form(""),
    g1_last_name: str = Form(""),
    g1_first_name: str = Form(""),
    g1_last_name_kana: str = Form(""),
    g1_first_name_kana: str = Form(""),
    g1_relationship: str = Form("父"),
    g1_phone: str = Form(""),
    g1_workplace: str = Form(""),
    g1_workplace_address: str = Form(""),
    g1_workplace_phone: str = Form(""),
    g2_last_name: str = Form(""),
    g2_first_name: str = Form(""),
    g2_last_name_kana: str = Form(""),
    g2_first_name_kana: str = Form(""),
    g2_relationship: str = Form("母"),
    g2_phone: str = Form(""),
    g2_workplace: str = Form(""),
    g2_workplace_address: str = Form(""),
    g2_workplace_phone: str = Form(""),
    session: Session = Depends(get_session),
):
    """園児を更新"""
    require_can_edit(current_user)
    stmt = select(Child).options(selectinload(Child.guardians), selectinload(Child.older_sibling)).where(Child.id == child_id)
    child = session.exec(stmt).first()
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")

    bd = _parse_date(birth_date)
    ed = _parse_date(enrollment_date)
    wd = _parse_date(withdrawal_date)
    if not bd or not ed:
        guardians = sorted(child.guardians, key=lambda g: g.order)
        g1 = guardians[0] if len(guardians) > 0 else None
        g2 = guardians[1] if len(guardians) > 1 else None
        # 編集フォーム用に仮のchildを作成（送信された値で上書き表示）
        from types import SimpleNamespace
        form_child = SimpleNamespace(
            last_name=last_name, first_name=first_name,
            last_name_kana=last_name_kana, first_name_kana=first_name_kana,
            birth_date=birth_date or None, enrollment_date=enrollment_date or None,
            withdrawal_date=withdrawal_date or None,
            status=SimpleNamespace(value=status),
            home_address=home_address or "", home_phone=home_phone or "",
            extra_data={"allergy": allergy.replace("、", ",").split(",") if allergy else [], "medical_notes": medical_notes or ""},
        )
        form_g1 = SimpleNamespace(last_name=g1_last_name, first_name=g1_first_name, last_name_kana=g1_last_name_kana,
                                  first_name_kana=g1_first_name_kana, relationship=g1_relationship, phone=g1_phone,
                                  workplace=g1_workplace, workplace_address=g1_workplace_address, workplace_phone=g1_workplace_phone) if (g1_last_name or g1_first_name) else None
        form_g2 = SimpleNamespace(last_name=g2_last_name, first_name=g2_first_name, last_name_kana=g2_last_name_kana,
                                  first_name_kana=g2_first_name_kana, relationship=g2_relationship, phone=g2_phone,
                                  workplace=g2_workplace, workplace_address=g2_workplace_address, workplace_phone=g2_workplace_phone) if (g2_last_name or g2_first_name) else None
        form_data = {"birth_date": birth_date, "enrollment_date": enrollment_date, "withdrawal_date": withdrawal_date or "",
                     "status": status, "last_name": last_name, "first_name": first_name,
                     "last_name_kana": last_name_kana, "first_name_kana": first_name_kana,
                     "home_address": home_address or "", "home_phone": home_phone or "",
                     "allergy": allergy, "medical_notes": medical_notes}
        return templates.TemplateResponse("children/form.html", {
            "request": request,
            "child": form_child,
            "guardian1": form_g1,
            "guardian2": form_g2,
            "action_url": f"/children/{child_id}/edit",
            "submit_label": "更新する",
            "page_title": f"{child.full_name} を編集",
            "inherit_from": None,
            "older_sibling_id": None,
            "all_children": [],
            "form_error": "生年月日と入園日は必須です。正しい日付を入力してください。",
            "form_data": form_data,
            "current_user": current_user,
        }, status_code=400)

    try:
        st = ChildStatus(status)
    except ValueError:
        st = ChildStatus.enrolled

    allergies = [a.strip() for a in allergy.replace("、", ",").split(",") if a.strip()]
    extra_data = {"allergy": allergies, "medical_notes": medical_notes or ""}

    child.last_name = last_name.strip()
    child.first_name = first_name.strip()
    child.last_name_kana = last_name_kana.strip()
    child.first_name_kana = first_name_kana.strip()
    child.birth_date = bd
    child.enrollment_date = ed
    child.withdrawal_date = wd
    child.status = st
    child.home_address = (home_address or "").strip() or None
    child.home_phone = (home_phone or "").strip() or None
    child.extra_data = extra_data
    child.updated_at = datetime.utcnow()
    session.add(child)

    # 保護者を削除して再登録
    for g in list(child.guardians):
        session.delete(g)
    session.flush()

    g1 = _parse_guardian(g1_last_name, g1_first_name, g1_last_name_kana, g1_first_name_kana,
                         g1_relationship, g1_phone, g1_workplace, g1_workplace_address, g1_workplace_phone)
    if g1:
        g1.child_id = child.id
        g1.order = 1
        session.add(g1)
    g2 = _parse_guardian(g2_last_name, g2_first_name, g2_last_name_kana, g2_first_name_kana,
                         g2_relationship, g2_phone, g2_workplace, g2_workplace_address, g2_workplace_phone)
    if g2:
        g2.child_id = child.id
        g2.order = 2
        session.add(g2)

    session.commit()
    return RedirectResponse(url="/children/", status_code=303)
