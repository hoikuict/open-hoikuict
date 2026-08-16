from __future__ import annotations

import argparse
import sys

from sqlmodel import Session, select

import database
from database import create_db_and_tables
from local_auth import (
    ACTION_CODE_TTL_MINUTES,
    bootstrap_admin,
    issue_existing_staff_activation,
)
from models import PasswordCredential, User
from staff_user_service import STAFF_USER_SORT_ORDER_LIMIT


def _required_prompt(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"{label}は必須です。", file=sys.stderr)


def bootstrap_admin_command() -> int:
    print("初期管理者を作成します。パスワードはこのCLIでは入力しません。")
    display_name = _required_prompt("表示名")
    email = _required_prompt("連絡先メールアドレス")
    login_id = _required_prompt("ログインID")
    reason = _required_prompt("作成理由")
    actor = _required_prompt("実行者")
    approver = _required_prompt("承認者")
    if input("この内容で作成しますか [yes/N]: ").strip().casefold() != "yes":
        print("中止しました。")
        return 1

    create_db_and_tables()
    try:
        with Session(database.engine) as session:
            user, activation_code = bootstrap_admin(
                session,
                display_name=display_name,
                email=email,
                login_id=login_id,
                reason=reason,
                actor=actor,
                approver=approver,
            )
    except ValueError as exc:
        print(f"作成できませんでした: {exc}", file=sys.stderr)
        return 2

    print(f"初期管理者を作成しました: user_id={user.id}")
    print(
        "次の有効化コードは今だけ表示されます。"
        f"有効期限は{ACTION_CODE_TTL_MINUTES}分です。"
    )
    print(activation_code)
    print("/staff/activate で本人がパスワードを設定してください。")
    return 0


def activate_existing_staff_command() -> int:
    create_db_and_tables()
    with Session(database.engine) as session:
        users = session.exec(
            select(User)
            .where(
                User.is_active.is_(True),
                User.staff_sort_order < STAFF_USER_SORT_ORDER_LIMIT,
            )
            .order_by(User.staff_sort_order, User.display_name, User.email)
        ).all()
        if not users:
            print("有効な職員が存在しません。", file=sys.stderr)
            return 2

        print("認証を有効化する既存職員を選択してください。")
        for index, user in enumerate(users, start=1):
            credential = session.exec(
                select(PasswordCredential).where(
                    PasswordCredential.staff_user_id == user.id
                )
            ).first()
            if credential is None:
                status = "認証未設定"
            elif credential.password_hash is None:
                status = "有効化待ち"
            elif credential.disabled_at is not None:
                status = "認証停止中"
            else:
                status = "認証設定済み"
            print(
                f"{index}. {user.display_name} <{user.email}> "
                f"[{user.staff_role} / {status}]"
            )

        raw_selection = input("番号: ").strip()
        try:
            selected_index = int(raw_selection) - 1
            if not 0 <= selected_index < len(users):
                raise IndexError
            user = users[selected_index]
        except (ValueError, IndexError):
            print("職員番号が不正です。", file=sys.stderr)
            return 2

        credential = session.exec(
            select(PasswordCredential).where(
                PasswordCredential.staff_user_id == user.id
            )
        ).first()
        default_login_id = credential.login_id if credential else user.email
        login_id = input(f"ログインID [{default_login_id}]: ").strip() or default_login_id
        reason = _required_prompt("発行理由")
        actor = _required_prompt("実行者")
        approver = _required_prompt("承認者")
        selected_display_name = user.display_name
        if input("有効化コードを発行しますか [yes/N]: ").strip().casefold() != "yes":
            print("中止しました。")
            return 1

        try:
            _, activation_code = issue_existing_staff_activation(
                session,
                user=user,
                login_id=login_id,
                reason=reason,
                actor=actor,
                approver=approver,
            )
        except ValueError as exc:
            print(f"発行できませんでした: {exc}", file=sys.stderr)
            return 2

    print(f"{selected_display_name} の有効化コードを発行しました。")
    print(
        "次のコードは今だけ表示されます。"
        f"有効期限は{ACTION_CODE_TTL_MINUTES}分です。"
    )
    print(activation_code)
    print("/staff/activate で本人がパスワードを設定してください。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auth-user")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "bootstrap-admin",
        help="空のDBへ最初の管理者と有効化コードを作成します",
    )
    subparsers.add_parser(
        "activate-staff",
        help="既存の職員へローカル認証の有効化コードを発行します",
    )
    args = parser.parse_args(argv)
    if args.command == "bootstrap-admin":
        return bootstrap_admin_command()
    if args.command == "activate-staff":
        return activate_existing_staff_command()
    parser.error("未対応のコマンドです")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
