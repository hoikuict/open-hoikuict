from datetime import date, datetime
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel
from time_utils import utc_now


class KioskAccount(SQLModel, table=True):
    __tablename__ = "class_kiosk_accounts"
    id: int | None = Field(default=None, primary_key=True)
    classroom_id: int = Field(foreign_key="classrooms.id", unique=True)
    active: bool = True


class KioskDevice(SQLModel, table=True):
    __tablename__ = "class_kiosk_devices"
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="class_kiosk_accounts.id", index=True)
    name: str
    token_hash: str = Field(unique=True)
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class KioskEnrollment(SQLModel, table=True):
    __tablename__ = "class_kiosk_enrollments"
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="class_kiosk_accounts.id")
    name: str
    code_hash: str = Field(unique=True)
    created_by: str
    expires_at: datetime
    used_at: datetime | None = None


class KioskAttempt(SQLModel, table=True):
    __tablename__ = "class_kiosk_attempts"
    id: int | None = Field(default=None, primary_key=True)
    source_hash: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class KioskOperation(SQLModel, table=True):
    __tablename__ = "class_kiosk_operations"
    __table_args__ = (UniqueConstraint("device_id", "request_id"),)
    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="class_kiosk_devices.id")
    request_id: str
    kind: str
    digest: str
    result: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class KioskAudit(SQLModel, table=True):
    __tablename__ = "class_kiosk_audits"
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="class_kiosk_accounts.id")
    device_id: int | None = Field(default=None, foreign_key="class_kiosk_devices.id")
    actor_name: str
    kind: str
    detail: dict = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now)


class KioskMessageOwner(SQLModel, table=True):
    __tablename__ = "class_kiosk_message_owners"
    message_id: int = Field(primary_key=True, foreign_key="messages.id")
    account_id: int = Field(foreign_key="class_kiosk_accounts.id")
    device_id: int = Field(foreign_key="class_kiosk_devices.id")


class KioskChange(SQLModel, table=True):
    __tablename__ = "class_kiosk_changes"
    __table_args__ = (UniqueConstraint("account_id", "child_id", "day", "kind"),)
    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="class_kiosk_accounts.id", index=True)
    child_id: int = Field(foreign_key="children.id")
    day: date
    kind: str
    version: str
    acknowledged: bool = False
    updated_at: datetime = Field(default_factory=utc_now)
    history: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class KioskSubscription(SQLModel, table=True):
    __tablename__ = "class_kiosk_subscriptions"
    device_id: int = Field(primary_key=True, foreign_key="class_kiosk_devices.id")
    endpoint: str = Field(unique=True)
    p256dh_key: str
    auth_key: str
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class KioskDelivery(SQLModel, table=True):
    __tablename__ = "class_kiosk_deliveries"
    __table_args__ = (UniqueConstraint("device_id", "event_key"),)
    id: int | None = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="class_kiosk_devices.id", index=True)
    event_key: str
    change_id: int | None = Field(default=None, foreign_key="class_kiosk_changes.id")
    version: str = ""
    state: str = "queued"
    attempts: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    next_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    provider_code: int | None = None
