"""Import staff directory entries without issuing credentials or permissions."""
from uuid import UUID

from sqlalchemy import func
from sqlmodel import select

from family_csv import add_diff, valid_email
from models import User
from time_utils import utc_now


STAFF_HEADERS = ("ID", "表示名", "メールアドレス", "表示順")


def plan_staff(session, rows, result, *, commit):
    from data_transfer_service import TransferMessage

    seen = set()
    for number, row in rows:
        try:
            matches = session.exec(select(User).where(func.lower(User.email) == row["メールアドレス"].lower())).all() if row["メールアドレス"] else []
            if not row["ID"] and len(matches) > 1:
                raise ValueError("同じメールの職員が複数います。職員IDを指定してください。")
            user = session.get(User, UUID(row["ID"])) if row["ID"] else (matches[0] if matches else None)
            if row["ID"] and user is None:
                raise ValueError("指定された職員IDが見つかりません。")
            if user and not user.is_active:
                raise ValueError("削除済み職員の復帰は職員管理画面で行ってください。")
            name = row["表示名"] or (user.display_name if user else "")
            email = row["メールアドレス"] or (user.email if user else "")
            order = int(row["表示順"]) if row["表示順"] else (user.staff_sort_order if user else 100)
            if not name or len(name) > 100 or not valid_email(email) or order < 1:
                raise ValueError("表示名、メールアドレス、1以上の表示順を確認してください。")
            if user and email != user.email:
                raise ValueError("既存職員のメール変更は職員管理画面で行ってください。")
            key = str(user.id) if user else email.lower()
            if key in seen:
                raise ValueError("ファイル内で同じ職員が重複しています。")
            seen.add(key)
        except ValueError as exc:
            result.errors.append(TransferMessage(number, "職員", "", str(exc)))
            continue
        values = {"display_name": name, "email": email, "staff_sort_order": order}
        add_diff(result, number, "職員", user.id if user else "新規",
                 {key: getattr(user, key) for key in values} if user else {}, values)
        if user:
            result.update_count += 1
        else:
            result.create_count += 1
        if commit:
            if not user:
                user = User(**values, staff_role="view_only", provisioning_source="manual")
            else:
                for key, value in values.items():
                    setattr(user, key, value)
                user.updated_at = utc_now()
            session.add(user)
