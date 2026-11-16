"""Child call orders and read-only fallback to previously registered family orders."""
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from models import Child, ChildStatus, ChildEmergencyOrder, FamilyEmergencyOrder
from time_utils import utc_now


def may_share(parent, child=None):
    family = parent.family
    if not family or (child and child.family_id != family.id):
        return False
    linked = {link.child_id for link in parent.child_links}
    enrolled = {c.id for c in family.children if c.status == ChildStatus.enrolled}
    return bool(enrolled) and enrolled <= linked and (child is None or child.id in linked)


def linked_to(parent, child):
    return any(link.child_id == child.id for link in parent.child_links)


def child_orders(child):
    return select(ChildEmergencyOrder).where(
        ChildEmergencyOrder.child_id == child.id, ChildEmergencyOrder.family_key == (child.family_id or 0)
    ).order_by(ChildEmergencyOrder.revision.desc())


def load_orders(session: Session, child, day=None, *, legacy=True):
    def current(scope):
        row = session.exec(child_orders(child).where(ChildEmergencyOrder.scope == scope).limit(1)).first()
        if row or not legacy or not child.family_id:
            return row
        return session.get(FamilyEmergencyOrder, (child.family_id, scope))

    usual = current("usual")
    answer = current(day.isoformat()) if day else None
    def revision(row):
        if isinstance(row, FamilyEmergencyOrder):
            return -row.revision
        return row.revision if row else 0
    return dict(usual=usual, answer=answer, base_revision=revision(usual), day_revision=revision(answer),
                legacy_usual=isinstance(usual, FamilyEmergencyOrder), legacy_answer=isinstance(answer, FamilyEmergencyOrder))


def base_editor_context(child, state, directory_allowed):
    profiles = child.family.guardian_profiles() if directory_allowed and child.family else []
    profiles = [p for p in profiles if any(p.get(k) for k in ("first_name", "last_name", "phone", "workplace_phone"))]
    roles = [str(p.get("relationship") or "").strip() for p in profiles]
    indexes = sorted(range(len(profiles)), key=lambda i: {"母": 0, "父": 1}.get(roles[i], 2))
    candidates = []
    for field in ("workplace_phone", "phone"):
        for i in indexes:
            profile = profiles[i]
            phone = str(profile.get(field) or "").strip()
            if not phone:
                continue
            name = " ".join(str(profile[k]).strip() for k in ("last_name", "first_name") if profile.get(k))
            role = roles[i]
            label = role if role and role != "保護者" and roles.count(role) == 1 else name or f"保護者{i+1}"
            digits = re.sub(r"[\s()ー−-]", "", unicodedata.normalize("NFKC", phone))
            kind = "職場" if field == "workplace_phone" else "携帯" if re.fullmatch(r"0[789]0\d{8}", digits) else "電話"
            candidates.append({"label": f"{label}の{kind}", "phone": phone})
    initial = state["usual"].contacts if state["usual"] else list(candidates)
    if not state["usual"] and len(profiles) == 1:
        initial.append({"label": "", "phone": "", "optional_extra": True})
    return dict(initial=initial or [{"label": "", "phone": ""}], candidates=candidates)


def contact_rows(labels, phones, *, skip_empty=False):
    if len(labels) != len(phones):
        raise HTTPException(400, "連絡先の名前と電話番号を確認してください。")
    rows = []
    for index, (label, phone) in enumerate(zip(labels, phones), 1):
        label, phone = label.strip(), unicodedata.normalize("NFKC", phone).strip()
        if skip_empty and not label and not phone:
            continue
        if not label or len(label) > 70:
            raise HTTPException(400, f"{index}番目の連絡先の名前を70文字以内で入れてください。")
        if len(phone) > 30 or not re.fullmatch(r"[0-9]{9,15}", re.sub(r"[\s()ー−-]", "", phone)):
            raise HTTPException(400, f"{index}番目の電話番号を市外局番から入れてください。")
        rows.append({"label": label, "phone": phone})
    if not rows:
        raise HTTPException(400, "連絡先を一つ以上入れてください。")
    return rows


def save_order(session, child, day, mode, labels, phones, base_revision, day_revision=0, *,
               author, source, actor_id=None, informant="", legacy=True):
    family_id = child.family_id
    # Serialize both first inserts and checks of the usual and date-specific revisions.
    lock = session.execute(update(Child).where(Child.id == child.id, Child.family_id == family_id)
                           .values(id=Child.id))
    if lock.rowcount != 1:
        raise HTTPException(409, "園児の登録が更新されました。画面を開き直してください。")
    state = load_orders(session, child, day, legacy=legacy)
    usual, answer = state["usual"], state["answer"]
    if base_revision != state["base_revision"] or day_revision != state["day_revision"]:
        raise HTTPException(409, "この園児の連絡順が更新されました。画面を開き直してください。")
    if day is None and mode == "base":
        rows = contact_rows(labels, phones, skip_empty=True)
    elif day and mode == "usual" and usual and usual.contacts:
        rows = list(usual.contacts)
    elif day and mode == "change":
        rows = contact_rows(labels, phones)
        base_contacts = usual.contacts if usual else []
        if source == "oral" and rows == base_contacts:
            mode = "usual"
        rows = [dict(row, day_only=row not in base_contacts) for row in rows]
    elif day and mode == "withdraw" and answer:
        rows = []
    else:
        raise HTTPException(400, "連絡の方法と、電話してほしい順番を確認してください。")
    revision = state["day_revision"] if day else state["base_revision"]
    session.add(ChildEmergencyOrder(child_id=child.id, family_key=family_id or 0, scope=day.isoformat() if day else "usual",
                                    revision=max(0, revision) + 1, contacts=rows, mode=mode, source=source,
                                    updated_at=utc_now(), updated_by=author, actor_id=actor_id, informant=informant))
