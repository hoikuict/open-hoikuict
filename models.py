from datetime import date, datetime
from enum import Enum
from typing import Any, List, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

from time_utils import utc_now


class ChildStatus(str, Enum):
    enrolled = "enrolled"
    graduated = "graduated"
    withdrawn = "withdrawn"

    @property
    def label(self) -> str:
        return {
            self.enrolled: "在園",
            self.graduated: "卒園",
            self.withdrawn: "退園",
        }[self]


class ParentAccountStatus(str, Enum):
    active = "active"
    inactive = "inactive"

    @property
    def label(self) -> str:
        return {
            self.active: "有効",
            self.inactive: "停止中",
        }[self]


class DailyContactEntryStatus(str, Enum):
    submitted = "submitted"

    @property
    def label(self) -> str:
        return {self.submitted: "提出済み"}[self]


class ParentContactType(str, Enum):
    present = "present"
    absent_private = "absent_private"
    absent_sick = "absent_sick"

    @property
    def label(self) -> str:
        return {
            self.present: "出席",
            self.absent_private: "欠席(私用)",
            self.absent_sick: "欠席(病欠)",
        }[self]

    @property
    def short_label(self) -> str:
        return {
            self.present: "出席",
            self.absent_private: "私用",
            self.absent_sick: "病欠",
        }[self]


class AttendanceVerificationStatus(str, Enum):
    present = "present"
    private_absent = "private_absent"
    sick_absent = "sick_absent"
    unknown = "unknown"

    @property
    def label(self) -> str:
        return {
            self.present: "出席",
            self.private_absent: "私用休み",
            self.sick_absent: "病気休み",
            self.unknown: "不明",
        }[self]

    @property
    def is_present(self) -> bool:
        return self == self.present

    @property
    def is_absent(self) -> bool:
        return self in {self.private_absent, self.sick_absent}

    @property
    def is_unknown(self) -> bool:
        return self == self.unknown


class ChildProfileChangeRequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"

    @property
    def label(self) -> str:
        return {
            self.pending: "承認待ち",
            self.approved: "承認済み",
            self.rejected: "差し戻し",
        }[self]


class NoticeStatus(str, Enum):
    draft = "draft"
    published = "published"

    @property
    def label(self) -> str:
        return {
            self.draft: "下書き",
            self.published: "公開中",
        }[self]


class NoticePriority(str, Enum):
    normal = "normal"
    high = "high"

    @property
    def label(self) -> str:
        return {
            self.normal: "通常",
            self.high: "重要",
        }[self]


class NoticeTargetType(str, Enum):
    all = "all"
    classroom = "classroom"
    child = "child"

    @property
    def label(self) -> str:
        return {
            self.all: "全保護者",
            self.classroom: "クラス",
            self.child: "園児",
        }[self]


CHILD_FIELDS = [
    {"key": "family_name", "label": "家族", "default": True},
    {"key": "classroom", "label": "クラス", "default": True},
    {"key": "last_name", "label": "姓", "default": True},
    {"key": "first_name", "label": "名", "default": True},
    {"key": "last_name_kana", "label": "姓（カナ）", "default": True},
    {"key": "first_name_kana", "label": "名（カナ）", "default": True},
    {"key": "birth_date", "label": "生年月日", "default": True},
    {"key": "age", "label": "年齢", "default": True},
    {"key": "enrollment_date", "label": "入園日", "default": False},
    {"key": "withdrawal_date", "label": "退園日", "default": False},
    {"key": "status", "label": "在籍状況", "default": True},
    {"key": "home_address", "label": "自宅住所", "default": False},
    {"key": "home_phone", "label": "自宅電話番号", "default": False},
    {"key": "guardians", "label": "保護者", "default": True},
    {"key": "siblings", "label": "兄弟姉妹", "default": False},
    {"key": "allergy", "label": "アレルギー", "default": False},
    {"key": "medical_notes", "label": "医療メモ", "default": False},
]


class Family(SQLModel, table=True):
    __tablename__ = "families"

    id: Optional[int] = Field(default=None, primary_key=True)
    family_name: str = Field(index=True)
    home_address: Optional[str] = None
    home_phone: Optional[str] = None
    shared_profile: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    children: List["Child"] = Relationship(back_populates="family")
    parent_accounts: List["ParentAccount"] = Relationship(back_populates="family")

    def guardian_profiles(self) -> list[dict[str, Any]]:
        profile = self.shared_profile if isinstance(self.shared_profile, dict) else {}
        guardians = profile.get("guardians", [])
        if not isinstance(guardians, list):
            return []
        return sorted(
            [item for item in guardians if isinstance(item, dict)],
            key=lambda item: int(item.get("order", 99)),
        )


class Classroom(SQLModel, table=True):
    __tablename__ = "classrooms"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    display_order: int = Field(default=1, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    children: List["Child"] = Relationship(back_populates="classroom")
    messages: List["Message"] = Relationship(back_populates="room")


class Child(SQLModel, table=True):
    __tablename__ = "children"

    id: Optional[int] = Field(default=None, primary_key=True)
    last_name: str
    first_name: str
    last_name_kana: str
    first_name_kana: str
    birth_date: date
    enrollment_date: date
    withdrawal_date: Optional[date] = None
    status: ChildStatus = Field(default=ChildStatus.enrolled)
    classroom_id: Optional[int] = Field(default=None, foreign_key="classrooms.id")
    family_id: Optional[int] = Field(default=None, foreign_key="families.id", index=True)
    home_address: Optional[str] = None
    home_phone: Optional[str] = None
    older_sibling_id: Optional[int] = Field(default=None, foreign_key="children.id")
    extra_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    older_sibling: Optional["Child"] = Relationship(
        back_populates="younger_siblings",
        sa_relationship_kwargs={"foreign_keys": "[Child.older_sibling_id]", "remote_side": "[Child.id]"},
    )
    younger_siblings: List["Child"] = Relationship(
        back_populates="older_sibling",
        sa_relationship_kwargs={"foreign_keys": "[Child.older_sibling_id]"},
    )
    classroom: Optional[Classroom] = Relationship(back_populates="children")
    family: Optional[Family] = Relationship(back_populates="children")
    guardians: List["Guardian"] = Relationship(back_populates="child")
    attendance_records: List["AttendanceRecord"] = Relationship(back_populates="child")
    parent_links: List["ParentChildLink"] = Relationship(back_populates="child")
    daily_contact_entries: List["DailyContactEntry"] = Relationship(back_populates="child")
    profile_change_requests: List["ChildProfileChangeRequest"] = Relationship(back_populates="child")

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"

    @property
    def full_name_kana(self) -> str:
        return f"{self.last_name_kana} {self.first_name_kana}"

    @property
    def age(self) -> int:
        today = date.today()
        return today.year - self.birth_date.year - (
            (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
        )

    @property
    def family_display_name(self) -> str:
        return self.family.family_name if self.family else ""

    @property
    def shared_home_address(self) -> str:
        if self.family and self.family.home_address:
            return self.family.home_address
        return self.home_address or ""

    @property
    def shared_home_phone(self) -> str:
        if self.family and self.family.home_phone:
            return self.family.home_phone
        return self.home_phone or ""

    def _guardian_labels(self) -> list[str]:
        family_labels: list[str] = []
        if self.family:
            for guardian_profile in self.family.guardian_profiles():
                last_name = str(guardian_profile.get("last_name", "")).strip()
                first_name = str(guardian_profile.get("first_name", "")).strip()
                if not last_name and not first_name:
                    continue
                label = f"{last_name} {first_name}".strip()
                relationship = str(guardian_profile.get("relationship", "")).strip()
                if relationship:
                    label = f"{label}（{relationship}）"
                family_labels.append(label)
        if family_labels:
            return family_labels

        guardian_labels: list[str] = []
        for guardian in sorted(self.guardians, key=lambda item: item.order):
            label = guardian.full_name
            if guardian.relationship:
                label = f"{label}（{guardian.relationship}）"
            guardian_labels.append(label)
        if guardian_labels:
            return guardian_labels

        account_labels: list[str] = []
        for account in sorted(self.parent_links, key=lambda item: (not item.is_primary_contact, item.id or 0)):
            if not account.parent_account:
                continue
            label = account.parent_account.display_name
            if account.relationship_label:
                label = f"{label}（{account.relationship_label}）"
            account_labels.append(label)
        if account_labels:
            return account_labels

        if self.family:
            return [
                account.display_name.strip()
                for account in sorted(self.family.parent_accounts, key=lambda item: item.id or 0)
                if account.display_name.strip()
            ]

        return []

    def get_field(self, key: str) -> str:
        if key == "family_name":
            return self.family_display_name
        if key == "classroom":
            return self.classroom.name if self.classroom else ""
        if key == "age":
            return f"{self.age}歳"
        if key == "status":
            return self.status.label
        if key == "home_address":
            return self.shared_home_address
        if key == "home_phone":
            return self.shared_home_phone
        if key == "allergy":
            if isinstance(self.extra_data, dict):
                return ", ".join(self.extra_data.get("allergy", []))
            return ""
        if key == "medical_notes":
            if isinstance(self.extra_data, dict):
                return str(self.extra_data.get("medical_notes", "") or "")
            return ""
        if key == "guardians":
            return " / ".join(self._guardian_labels())
        if key == "siblings":
            if self.older_sibling:
                return f"兄姉: {self.older_sibling.full_name}"
            younger_names = [sibling.full_name for sibling in self.younger_siblings]
            return " / ".join(younger_names)
        value = getattr(self, key, None)
        return str(value) if value is not None else ""


class Guardian(SQLModel, table=True):
    __tablename__ = "guardians"

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id")
    last_name: str
    first_name: str
    last_name_kana: Optional[str] = None
    first_name_kana: Optional[str] = None
    relationship: str = "母"
    phone: Optional[str] = None
    workplace: Optional[str] = None
    workplace_address: Optional[str] = None
    workplace_phone: Optional[str] = None
    order: int = 1

    child: Optional[Child] = Relationship(back_populates="guardians")

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"


class AttendanceRecord(SQLModel, table=True):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("child_id", "attendance_date", name="uq_attendance_child_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    attendance_date: date = Field(index=True)
    check_in_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    planned_pickup_time: Optional[str] = None
    pickup_person: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    child: Optional[Child] = Relationship(back_populates="attendance_records")


class ParentAccount(SQLModel, table=True):
    __tablename__ = "parent_accounts"

    id: Optional[int] = Field(default=None, primary_key=True)
    display_name: str
    email: str = Field(index=True, unique=True)
    phone: Optional[str] = None
    home_address: Optional[str] = None
    workplace: Optional[str] = None
    workplace_address: Optional[str] = None
    workplace_phone: Optional[str] = None
    family_id: Optional[int] = Field(default=None, foreign_key="families.id", index=True)
    status: ParentAccountStatus = Field(default=ParentAccountStatus.active)
    password_hash: Optional[str] = None
    invited_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    family: Optional[Family] = Relationship(back_populates="parent_accounts")
    child_links: List["ParentChildLink"] = Relationship(back_populates="parent_account")
    daily_contact_entries: List["DailyContactEntry"] = Relationship(back_populates="parent_account")
    notice_reads: List["NoticeRead"] = Relationship(back_populates="parent_account")
    profile_change_notifications: List["ProfileChangeNotification"] = Relationship(back_populates="parent_account")
    child_profile_change_requests: List["ChildProfileChangeRequest"] = Relationship(back_populates="parent_account")

    @property
    def family_display_name(self) -> str:
        return self.family.family_name if self.family else ""


class ParentChildLink(SQLModel, table=True):
    __tablename__ = "parent_child_links"
    __table_args__ = (UniqueConstraint("parent_account_id", "child_id", name="uq_parent_child_link"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    relationship_label: str = Field(default="保護者")
    is_primary_contact: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    parent_account: Optional[ParentAccount] = Relationship(back_populates="child_links")
    child: Optional[Child] = Relationship(back_populates="parent_links")


class DailyContactEntry(SQLModel, table=True):
    __tablename__ = "daily_contact_entries"
    __table_args__ = (UniqueConstraint("child_id", "target_date", name="uq_daily_contact_child_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    target_date: date = Field(index=True)
    temperature: Optional[str] = None
    sleep_notes: Optional[str] = None
    breakfast_status: Optional[str] = None
    bowel_movement_status: Optional[str] = None
    mood: Optional[str] = None
    cough: Optional[str] = None
    runny_nose: Optional[str] = None
    medication: Optional[str] = None
    condition_note: Optional[str] = None
    contact_note: Optional[str] = None
    contact_type: ParentContactType = Field(default=ParentContactType.present)
    absence_temperature: Optional[str] = None
    absence_symptoms: Optional[str] = None
    absence_diagnosis: Optional[str] = None
    absence_note: Optional[str] = None
    status: DailyContactEntryStatus = Field(default=DailyContactEntryStatus.submitted)
    extra_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    submitted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    child: Optional[Child] = Relationship(back_populates="daily_contact_entries")
    parent_account: Optional[ParentAccount] = Relationship(back_populates="daily_contact_entries")


    @property
    def is_present_contact(self) -> bool:
        return self.contact_type == ParentContactType.present

    @property
    def is_absent_contact(self) -> bool:
        return self.contact_type in {ParentContactType.absent_private, ParentContactType.absent_sick}

    @property
    def absence_reason_label(self) -> str:
        if self.contact_type == ParentContactType.absent_private:
            return "私用"
        if self.contact_type == ParentContactType.absent_sick:
            return "病欠"
        return ""


class AttendanceVerification(SQLModel, table=True):
    __tablename__ = "attendance_verifications"
    __table_args__ = (UniqueConstraint("child_id", "target_date", name="uq_attendance_verification_child_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    target_date: date = Field(index=True)
    status: AttendanceVerificationStatus = Field(default=AttendanceVerificationStatus.unknown)
    updated_by_name: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AttendanceVerificationHistory(SQLModel, table=True):
    __tablename__ = "attendance_verification_histories"

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    target_date: date = Field(index=True)
    status: AttendanceVerificationStatus = Field(default=AttendanceVerificationStatus.unknown)
    updated_by_name: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class AttendanceAlarmState(SQLModel, table=True):
    __tablename__ = "attendance_alarm_states"
    __table_args__ = (UniqueConstraint("child_id", "target_date", name="uq_attendance_alarm_child_date"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    target_date: date = Field(index=True)
    is_active: bool = Field(default=False, index=True)
    reasons: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    evaluated_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AttendanceAlarmHistory(SQLModel, table=True):
    __tablename__ = "attendance_alarm_histories"

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    target_date: date = Field(index=True)
    is_active: bool = Field(default=False, index=True)
    reasons: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    evaluated_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)


class Notice(SQLModel, table=True):
    __tablename__ = "notices"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    body: str
    priority: NoticePriority = Field(default=NoticePriority.normal)
    status: NoticeStatus = Field(default=NoticeStatus.draft)
    publish_start_at: Optional[datetime] = None
    publish_end_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    targets: List["NoticeTarget"] = Relationship(back_populates="notice")
    reads: List["NoticeRead"] = Relationship(back_populates="notice")


class MeetingNote(SQLModel, table=True):
    __tablename__ = "meeting_notes"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(default="無題の議事録")
    content: Optional[bytes] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class NoticeTarget(SQLModel, table=True):
    __tablename__ = "notice_targets"

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    target_type: NoticeTargetType = Field(default=NoticeTargetType.all)
    target_value: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    notice: Optional[Notice] = Relationship(back_populates="targets")


class NoticeRead(SQLModel, table=True):
    __tablename__ = "notice_reads"
    __table_args__ = (UniqueConstraint("notice_id", "parent_account_id", name="uq_notice_parent_read"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    read_at: datetime = Field(default_factory=utc_now)

    notice: Optional[Notice] = Relationship(back_populates="reads")
    parent_account: Optional[ParentAccount] = Relationship(back_populates="notice_reads")


class ProfileChangeNotification(SQLModel, table=True):
    __tablename__ = "profile_change_notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    change_summary: str
    change_details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)
    read_at: Optional[datetime] = None

    parent_account: Optional[ParentAccount] = Relationship(back_populates="profile_change_notifications")


class ChildProfileChangeRequest(SQLModel, table=True):
    __tablename__ = "child_profile_change_requests"

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    status: ChildProfileChangeRequestStatus = Field(
        default=ChildProfileChangeRequestStatus.pending,
        index=True,
    )
    change_summary: str
    request_data: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    change_details: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    submitted_at: datetime = Field(default_factory=utc_now)
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None
    updated_at: datetime = Field(default_factory=utc_now)

    child: Optional[Child] = Relationship(back_populates="profile_change_requests")
    parent_account: Optional[ParentAccount] = Relationship(back_populates="child_profile_change_requests")


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_id: int = Field(foreign_key="classrooms.id", index=True)
    parent_message_id: Optional[int] = Field(default=None, foreign_key="messages.id", index=True)
    author_name: str
    body: str = Field(default="")
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
    deleted_at: Optional[datetime] = Field(default=None, index=True)
    deleted_by: Optional[str] = None

    room: Optional[Classroom] = Relationship(back_populates="messages")
    attachments: List["MessageAttachment"] = Relationship(back_populates="message")

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def display_body(self) -> str:
        if self.is_deleted:
            return "このメッセージは削除されました。"
        return self.body


class MessageAttachment(SQLModel, table=True):
    __tablename__ = "message_attachments"

    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: int = Field(foreign_key="messages.id", index=True)
    original_filename: str
    storage_path: str
    content_type: Optional[str] = None
    file_size: int = Field(default=0)
    is_image: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now)

    message: Optional[Message] = Relationship(back_populates="attachments")
