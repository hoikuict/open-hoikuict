"""Remove a registered address while preserving account and activity references."""
import re
from uuid import uuid4

from sqlmodel import Session, select

from models import (Child, ChildProfileChangeRequest, ChildProfileHistory, Family, Guardian, ParentAddressRemoval,
                    ParentAccountStatus, ParentEnrollment, ParentMailDelivery,
                    ParentRegistrationRequest, ProfileChangeNotification)
from parent_auth import suspend_parent_authentication
from time_utils import utc_now


def remove_parent_address(session: Session, account, *, actor, reason: str) -> None:
    if account.email_removed:
        return
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValueError("削除理由を500文字以内で入力してください")
    pattern = re.compile(r"(?<![\w.+@-])" + re.escape(account.email) + r"(?![\w.@-])", re.IGNORECASE)

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return pattern.sub("", value) if isinstance(value, str) else value

    now = utc_now()
    account.status = ParentAccountStatus.inactive
    credential = suspend_parent_authentication(session, account, reason="email_removed", now=now)
    # The required unique key is replaced by a non-address identifier. No old address is retained here.
    account.email = "removed:" + uuid4().hex
    account.password_hash = None
    account.updated_at = now
    session.add(account)
    if credential:
        credential.login_id = credential.login_id_normalized = account.email
        credential.password_hash = None
        session.add(credential)
    registrations = session.exec(select(ParentRegistrationRequest).where(
        ParentRegistrationRequest.parent_account_id == account.id)).all()
    for registration in registrations:
        registration.email_normalized_snapshot = ""
        session.add(registration)
        enrollment = session.get(ParentEnrollment, registration.id)
        if enrollment:
            enrollment.source_snapshot = scrub(enrollment.source_snapshot)
            enrollment.submitted_data = scrub(enrollment.submitted_data)
            session.add(enrollment)
    for mail in session.exec(select(ParentMailDelivery).where(ParentMailDelivery.parent_account_id == account.id)).all():
        mail.recipient = ""
        mail.subject, mail.body = scrub(mail.subject), scrub(mail.body)
        if mail.status in {"pending", "processing", "retry"}:
            mail.status, mail.failure_code = "cancelled", "email_removed"
        session.add(mail)
    for notice in session.exec(select(ProfileChangeNotification).where(ProfileChangeNotification.parent_account_id == account.id)).all():
        notice.change_summary = scrub(notice.change_summary)
        notice.change_details = scrub(notice.change_details)
        session.add(notice)
    for guardian in session.exec(select(Guardian).where(Guardian.parent_account_id == account.id)).all():
        guardian.email = None
        session.add(guardian)
    if account.family_id is not None:
        family = session.get(Family, account.family_id)
        if family:
            family.shared_profile = scrub(family.shared_profile)
            family.updated_at = now
            session.add(family)
        children = session.exec(select(Child).where(Child.family_id == account.family_id)).all()
        for child in children:
            child.extra_data = scrub(child.extra_data)
            session.add(child)
            for guardian in session.exec(select(Guardian).where(Guardian.child_id == child.id)).all():
                guardian.email = scrub(guardian.email) or None
                session.add(guardian)
            for history in session.exec(select(ChildProfileHistory).where(ChildProfileHistory.child_id == child.id)).all():
                history.snapshot, history.changes = scrub(history.snapshot), scrub(history.changes)
                session.add(history)
            for change in session.exec(select(ChildProfileChangeRequest).where(ChildProfileChangeRequest.child_id == child.id)).all():
                change.request_data, change.change_details = scrub(change.request_data), scrub(change.change_details)
                session.add(change)
            for enrollment in session.exec(select(ParentEnrollment).where(ParentEnrollment.child_id == child.id)).all():
                enrollment.source_snapshot = scrub(enrollment.source_snapshot)
                enrollment.submitted_data = scrub(enrollment.submitted_data)
                session.add(enrollment)
    session.add(ParentAddressRemoval(parent_account_id=account.id, actor_user_id=actor.user_id,
        actor_name=actor.name, reason=scrub(reason), created_at=now))
