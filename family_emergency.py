"""Family-wide call order and independent, date-specific snapshots."""
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session

from models import ChildStatus, Family, FamilyEmergencyOrder
from time_utils import utc_now


def may_share(parent, child=None):
    family = parent.family
    if not family or (child and child.family_id != family.id):
        return False
    linked = {link.child_id for link in parent.child_links}
    enrolled = {c.id for c in family.children if c.status == ChildStatus.enrolled}
    return bool(enrolled) and enrolled <= linked and (child is None or child.id in linked)


def load_orders(session: Session, family_id, day=None):
    def get(scope):
        return session.get(FamilyEmergencyOrder, (family_id, scope), populate_existing=True) if family_id else None
    usual = get("usual")
    answer = get(day.isoformat()) if day else None
    return {"usual": usual, "answer": answer}


def phone_candidates(family):
    result = []
    for profile in family.guardian_profiles():
        label = profile.get("relationship") or profile.get("last_name") or "保護者"
        for field, suffix in (("workplace_phone", "の職場"), ("phone", "の電話")):
            if profile.get(field):
                result.append({"label": label + suffix, "phone": profile[field]})
    return result


def contact_rows(labels, phones):
    if len(labels) != len(phones):
        raise HTTPException(400, "連絡先の名前と電話番号を確認してください。")
    rows = []
    for index, (label, phone) in enumerate(zip(labels, phones), 1):
        label, phone = label.strip(), unicodedata.normalize("NFKC", phone).strip()
        if not label or len(label) > 70:
            raise HTTPException(400, f"{index}番目の連絡先の名前を70文字以内で入れてください。")
        if len(phone) > 30 or not re.fullmatch(r"[0-9]{9,15}", re.sub(r"[\s()ー−-]", "", phone)):
            raise HTTPException(400, f"{index}番目の電話番号を市外局番から入れてください。")
        rows.append({"label": label, "phone": phone})
    if not rows:
        raise HTTPException(400, "連絡先を一つ以上入れてください。")
    return rows


def save_order(session, parent, day, mode, labels, phones, base_revision, day_revision=0):
    family_id = parent.family_id
    if not may_share(parent):
        raise HTTPException(403, "ご家族の緊急連絡先は園にご確認ください。")
    # Serialize checks across the usual order and all dated snapshots, including first insert.
    session.execute(update(Family).where(Family.id == family_id).values(updated_at=Family.updated_at))
    state = load_orders(session, family_id, day)
    usual, answer = state["usual"], state["answer"]
    if base_revision != (usual.revision if usual else 0) or day_revision != (answer.revision if answer else 0):
        raise HTTPException(409, "別の保護者が連絡先を更新しました。画面を開き直して最新の順番を確認してください。")
    if day is None and mode == "base":
        rows = contact_rows(labels, phones)
    elif day and mode == "usual" and usual and usual.contacts:
        rows = list(usual.contacts)
    elif day and mode == "change":
        rows = contact_rows(labels, phones)
        base_contacts = usual.contacts if usual else []
        rows = [dict(row, day_only=row not in base_contacts) for row in rows]
    elif day and mode == "withdraw" and answer:
        rows = []
    else:
        raise HTTPException(400, "連絡の方法と、電話してほしい順番を確認してください。")
    record = (answer if day else usual) or FamilyEmergencyOrder(
        family_id=family_id, scope=day.isoformat() if day else "usual", revision=0)
    record.mode, record.contacts = mode, rows
    record.revision += 1
    record.updated_by, record.updated_at = parent.display_name, utc_now()
    session.add(record)
