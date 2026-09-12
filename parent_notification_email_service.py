"""Optional email alongside attendance push, sharing the durable mail worker."""

import os

from sqlmodel import select

from models import (
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentEmailPreference,
    ParentMailDelivery,
    ParentNotification,
    ParentNotificationEmail,
)
from time_utils import ensure_utc, utc_now


def email_enabled(session, parent_id):
    preference = session.get(ParentEmailPreference, parent_id)
    return bool(preference and preference.attendance_confirmation_enabled)


def queue_notification_email(session, notification, expires_at):
    if not email_enabled(session, notification.parent_account_id) or session.get(
        ParentNotificationEmail, notification.id
    ):
        return
    account = session.get(ParentAccount, notification.parent_account_id)
    if account is None or account.status != ParentAccountStatus.active:
        return
    origin = os.getenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL", "").rstrip("/")
    link = (
        origin + notification.action_url
        if origin
        else "保護者ポータルへログインして確認してください。"
    )
    mail = ParentMailDelivery(
        parent_account_id=account.id,
        message_type="attendance_confirmation",
        recipient=account.email,
        subject=notification.title,
        body=f"{notification.body}\n\n{link}\n\nこのメールは出欠確認の通知設定に基づいて送信しています。",
    )
    session.add(mail)
    session.flush()
    session.add(
        ParentNotificationEmail(
            notification_id=notification.id, mail_id=mail.id, expires_at=expires_at
        )
    )


def notification_mail_is_current(session, delivery):
    link = session.exec(
        select(ParentNotificationEmail).where(
            ParentNotificationEmail.mail_id == delivery.id
        )
    ).first()
    if not link or ensure_utc(link.expires_at) <= utc_now():
        return False
    notification = session.get(ParentNotification, link.notification_id)
    account = session.get(ParentAccount, delivery.parent_account_id)
    if (
        not notification
        or not account
        or account.status != ParentAccountStatus.active
        or account.email.casefold() != delivery.recipient.casefold()
    ):
        return False
    return bool(
        email_enabled(session, account.id)
        and session.exec(
            select(ParentChildLink).where(
                ParentChildLink.parent_account_id == account.id,
                ParentChildLink.child_id == notification.child_id,
            )
        ).first()
    )
