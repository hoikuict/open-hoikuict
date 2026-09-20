"""Persisted staff login policy; existing sessions retain their own timeouts."""
from dataclasses import dataclass
from decimal import Decimal, DecimalException

from sqlmodel import Session

from models import StaffSessionPolicy, StaffSessionPolicyAudit, User
from time_utils import utc_now


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    idle_minutes: int
    absolute_hours: int


def get_staff_session_policy(session: Session) -> SessionPolicy:
    policy = session.get(StaffSessionPolicy, 1)
    if policy is not None:
        return SessionPolicy(policy.idle_minutes, policy.absolute_hours)
    # Preserve the deployed environment until an administrator explicitly saves.
    from local_auth import _staff_absolute_hours, _staff_idle_minutes

    return SessionPolicy(_staff_idle_minutes(), _staff_absolute_hours())


def parse_session_policy(idle_value: str, idle_unit: str, absolute_hours: str) -> SessionPolicy:
    if idle_unit not in {"minutes", "hours"}:
        raise ValueError("非操作時間の単位を選択してください。")
    try:
        minutes = Decimal(idle_value) * (60 if idle_unit == "hours" else 1)
        absolute = int(absolute_hours)
    except (ValueError, TypeError, DecimalException) as exc:
        raise ValueError("非操作時間は数値、最長時間は整数で入力してください。") from exc
    if not minutes.is_finite() or not 4 < minutes < 1441:
        raise ValueError("非操作時間は5分〜24時間で入力してください。")
    rounded = minutes.to_integral_value()
    if abs(minutes - rounded) > Decimal("0.00001"):
        raise ValueError("非操作時間は分に換算して整数になる時間を入力してください。")
    idle = int(rounded)
    if not 5 <= idle <= 1440:
        raise ValueError("非操作時間は5分〜24時間で入力してください。")
    if not 1 <= absolute <= 24:
        raise ValueError("最長時間は1〜24時間で入力してください。")
    if idle > absolute * 60:
        raise ValueError("非操作時間は最長時間以下にしてください。")
    return SessionPolicy(idle, absolute)


def save_staff_session_policy(session: Session, policy: SessionPolicy, actor: User) -> None:
    policy = parse_session_policy(str(policy.idle_minutes), "minutes", str(policy.absolute_hours))
    before = get_staff_session_policy(session)
    record = session.get(StaffSessionPolicy, 1) or StaffSessionPolicy(id=1)
    record.idle_minutes = policy.idle_minutes
    record.absolute_hours = policy.absolute_hours
    record.updated_at = utc_now()
    record.updated_by_user_id = actor.id
    session.add(record)
    session.add(StaffSessionPolicyAudit(
        changed_by_user_id=actor.id,
        changed_by_name_snapshot=actor.display_name,
        old_idle_minutes=before.idle_minutes,
        old_absolute_hours=before.absolute_hours,
        new_idle_minutes=policy.idle_minutes,
        new_absolute_hours=policy.absolute_hours,
        changed_at=record.updated_at,
    ))
    session.commit()
