"""Capture membership changes before flush and synchronize them within commit."""
from types import SimpleNamespace

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlmodel import select

from child_care_certification_service import list_certifications
from family_care_service import _end_record, bootstrap, latest_common, materialize
from models import (Child, Family, FamilyCareAudit, FamilyCareChildSetting,
                    FamilyCareCertification, FamilyCareCertificationLink)
from time_utils import local_today
from datetime import timedelta


@event.listens_for(Session, "before_flush")
def remember_membership(session, context, instances):
    if session.info.get("family_care_syncing"):
        return
    for child in session.new | session.dirty:
        if not isinstance(child, Child):
            continue
        state = inspect(child)
        fields = ("family_id", "family", "enrollment_date", "withdrawal_date")
        if child in session.new or any(state.attrs[f].history.has_changes() for f in fields):
            pending = session.info.setdefault("family_care_members", {})
            pending.setdefault(id(child), (child, child in session.new))


@event.listens_for(Session, "before_commit")
def synchronize_membership(session):
    if session.info.get("family_care_syncing"):
        return
    session.flush()
    pending = session.info.pop("family_care_members", {})
    if not pending:
        return
    session.info["family_care_syncing"] = True
    actor = SimpleNamespace(name="家族・在籍情報の変更による自動反映", user_id=None)
    try:
        for child, is_new in pending.values():
            if child in session.deleted or inspect(child).deleted:
                continue
            setting = session.get(FamilyCareChildSetting, child.id)
            family_changed = setting and setting.family_id != child.family_id
            if family_changed:
                # Only end future use; a later family move cannot rewrite past dates.
                boundary = max(local_today(), child.enrollment_date)
                for cert in list_certifications(session, child.id):
                    link = session.get(FamilyCareCertificationLink, cert.id)
                    if link and cert.is_active and (cert.effective_to is None or cert.effective_to >= boundary):
                        _end_record(session, cert, boundary - timedelta(days=1), actor, "家族紐づけ変更")
                session.delete(setting)
                session.flush()
                setting = None
            family = session.get(Family, child.family_id) if child.family_id else None
            common = latest_common(session, family.id) if family else None
            if not common:
                continue
            if setting is None:
                individual = any(r.is_active and not session.get(FamilyCareCertificationLink, r.id)
                                 for r in list_certifications(session, child.id))
                setting = FamilyCareChildSetting(child_id=child.id, family_id=family.id,
                    mode="individual" if individual else "inherit",
                    joined_on=child.enrollment_date if is_new else max(local_today(), child.enrollment_date))
                session.add(setting)
            if setting.mode != "inherit":
                continue
            before = bootstrap(session, family)["store"]
            # Preserve an already materialized period on later profile edits.
            active = []
            for record in list_certifications(session, child.id):
                link = session.get(FamilyCareCertificationLink, record.id)
                source = session.get(FamilyCareCertification, link.family_certification_id) if link else None
                if record.is_active and source and source.family_id == family.id and (record.effective_to is None or record.effective_to >= setting.joined_on):
                    active.append(record)
            if active:
                for cert in active:
                    link = session.get(FamilyCareCertificationLink, cert.id)
                    if link and child.withdrawal_date and (cert.effective_to is None or cert.effective_to > child.withdrawal_date):
                        _end_record(session, cert, max(child.withdrawal_date, local_today()-timedelta(days=1)), actor, "在籍期間変更")
            else:
                # All current/future common periods are inherited for a newly joined child.
                records = session.exec(select(FamilyCareCertification).where(
                    FamilyCareCertification.family_id == family.id,
                    FamilyCareCertification.is_active == True).order_by(FamilyCareCertification.effective_from)).all()
                for record in records:
                    materialize(session, child, record.data, bootstrap(session, family)["guardians"],
                        actor, "家族共通認定を引継ぎ", source=record, floor=setting.joined_on)
            session.flush()
            after = bootstrap(session, family)["store"]
            if before != after:
                session.add(FamilyCareAudit(family_id=family.id, action="membership_sync",
                    before_snapshot=before, after_snapshot=after, reason="家族・在籍情報変更",
                    actor_name=actor.name))
    finally:
        session.info.pop("family_care_syncing", None)


@event.listens_for(Session, "after_rollback")
def clear_membership(session):
    session.info.pop("family_care_members", None)
