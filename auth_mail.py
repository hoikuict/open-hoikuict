"""SMTP transport shared by parent registration and staff account recovery."""

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_auth_mail(*, recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = os.environ["HOIKUICT_PARENT_MAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(
        os.environ["HOIKUICT_SMTP_HOST"],
        int(os.getenv("HOIKUICT_SMTP_PORT", "587")),
        timeout=20,
    ) as smtp:
        if os.getenv("HOIKUICT_SMTP_STARTTLS", "1") == "1":
            smtp.starttls(context=ssl.create_default_context())
        username = os.getenv("HOIKUICT_SMTP_USERNAME")
        if username:
            smtp.login(username, os.getenv("HOIKUICT_SMTP_PASSWORD") or "")
        smtp.send_message(message)
