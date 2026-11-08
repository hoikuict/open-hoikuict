import hashlib
import json

from fastapi import HTTPException
from sqlmodel import Session, select

from child_health_service import get_child_health_profile
from models import Child, ParentMedicalResponse


FIELDS = {
    "blood_type": "血液型",
    "primary_doctor_name": "かかりつけ医の名前",
    "primary_doctor_phone": "かかりつけ医の電話番号",
    "primary_doctor_address": "かかりつけ医の住所",
    "hospital_name": "希望する搬送先（任意）",
    "hospital_phone": "搬送先の電話番号",
}
BLOOD_TYPES = ("わからない", "A型", "B型", "O型", "AB型")
XRAY_QUESTION = "保育中のけがで受診し、医師がレントゲン撮影を必要と判断したとき、園から保護者に連絡がつかない場合はどうしますか？"
XRAY_CHOICES = {
    "agree": "連絡がつかない場合は、撮影を承諾します",
    "contact": "事前には承諾しません。撮影前に確認してください",
    "undecided": "今は決めません",
}
UNANSWERED = "未回答（事前承諾なし）"
STATES = {"requested": "記入のお願い", "pending": "園で確認中", "approved": "園で確認済み", "returned": "書き直しのお願い", "superseded": "再回答済み"}


def lock_child(session: Session, child_id: int) -> None:
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        session.exec(select(Child.id).where(Child.id == child_id).with_for_update()).first()


def current_values(session, child_id):
    profile = get_child_health_profile(session, child_id)
    return {key: getattr(profile, key, None) or "" for key in FIELDS}


def latest_answer(session, child_id, parent_id):
    return session.exec(select(ParentMedicalResponse).where(
        ParentMedicalResponse.child_id == child_id,
        ParentMedicalResponse.parent_account_id == parent_id,
    ).order_by(ParentMedicalResponse.id.desc())).first()


def latest_consent(session, child_id):
    return session.exec(select(ParentMedicalResponse).where(
        ParentMedicalResponse.child_id == child_id,
        ParentMedicalResponse.submitted_at.is_not(None),
    ).order_by(ParentMedicalResponse.submitted_at.desc(), ParentMedicalResponse.id.desc())).first()


def revision(child_id, parent_id, values, latest, consent):
    parts = [child_id, parent_id, values, (latest.id, latest.status) if latest else None,
             (consent.id, consent.status) if consent else None]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def staff_medical_context(session, child_id):
    return {"consent": latest_consent(session, child_id), "choices": XRAY_CHOICES,
            "statuses": STATES, "unanswered": UNANSWERED}


def require_current(expected, supplied):
    if expected != supplied:
        raise HTTPException(409, "内容が更新されました。画面を開き直して、最新の内容を確認してください。")


def form_answers(form, baseline):
    answers = {}
    for key in FIELDS:
        value = str(form.get(key) or "").strip()
        if len(value) > 300 and value != baseline[key]:
            raise ValueError(f"{FIELDS[key]}は300文字以内で入力してください。")
        answers[key] = value or baseline[key]
    if answers["blood_type"] not in ("", baseline["blood_type"], *BLOOD_TYPES):
        raise ValueError("血液型を選び直してください。")
    if form.get("clear_hospital") == "yes":
        answers["hospital_name"] = answers["hospital_phone"] = ""
    elif answers["hospital_name"] != baseline["hospital_name"] and not str(form.get("hospital_phone") or "").strip():
        answers["hospital_phone"] = ""
    if answers["hospital_phone"] and not answers["hospital_name"] and answers["hospital_phone"] != baseline["hospital_phone"]:
        raise ValueError("搬送先の電話番号を入力した場合は、病院名も入力してください。")
    xray = form.get("xray_answer") or None
    if xray is not None and xray not in XRAY_CHOICES:
        raise ValueError("レントゲン撮影の回答を選び直してください。")
    return answers, xray
