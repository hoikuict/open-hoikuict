from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


BOOTSTRAP_FIELDS = {
    "display_name": "表示名",
    "email": "連絡先メールアドレス",
    "login_id": "ログインID",
    "reason": "作成理由",
    "actor": "実行者",
    "approver": "承認者",
}
MAX_BOOTSTRAP_JSON_BYTES = 64 * 1024


def _validate_bootstrap_values(values: object) -> dict[str, str]:
    if not isinstance(values, dict) or set(values) != set(BOOTSTRAP_FIELDS):
        raise ValueError("JSONにはdisplay_name, email, login_id, reason, actor, approverだけを指定してください")
    result = {}
    for field, label in BOOTSTRAP_FIELDS.items():
        value = values[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}は空でない文字列で指定してください")
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ValueError(
                f"{label}の文字コードを確認できません。UTF-8のJSONファイルを--input-jsonで渡してください"
            ) from None
        result[field] = value.strip()
    return result


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("JSONの項目名が重複しています")
        values[key] = value
    return values


def _read_bootstrap_json(path: str) -> dict[str, str]:
    try:
        if path == "-":
            raw = sys.stdin.buffer.read(MAX_BOOTSTRAP_JSON_BYTES + 1)
        else:
            with Path(path).open("rb") as stream:
                raw = stream.read(MAX_BOOTSTRAP_JSON_BYTES + 1)
    except OSError:
        raise ValueError("JSONファイルを読み取れません。パスと読み取り権限を確認してください") from None
    if len(raw) > MAX_BOOTSTRAP_JSON_BYTES:
        raise ValueError("JSONファイルは64 KiB以下にしてください")
    try:
        values = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_json_object)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("UTF-8の正しいJSONファイルを指定してください") from None
    return _validate_bootstrap_values(values)


def _required_prompt(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"{label}は必須です。", file=sys.stderr)


def bootstrap_admin_command(*, input_json: str | None = None, yes: bool = False) -> int:
    print("初期管理者を作成します。パスワードはこのCLIでは入力しません。")
    try:
        if yes and input_json is None:
            raise ValueError("--yesは--input-jsonと一緒に指定してください")
        if input_json == "-" and not yes:
            raise ValueError("標準入力のJSONには、内容を確認してから--yesを指定してください")
        values = (
            _read_bootstrap_json(input_json) if input_json is not None
            else _validate_bootstrap_values({
                field: _required_prompt(label) for field, label in BOOTSTRAP_FIELDS.items()
            })
        )
        if not yes and input("この内容で作成しますか [yes/N]: ").strip().casefold() != "yes":
            print("中止しました。")
            return 1
    except (ValueError, EOFError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "入力が終了しました。JSON入力では--input-jsonを指定してください"
        print(f"作成できませんでした: {message}", file=sys.stderr)
        return 2

    create_db_and_tables()
    try:
        with Session(database.engine) as session:
            user, activation_code = bootstrap_admin(
                session,
                **values,
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
    bootstrap_parser = subparsers.add_parser(
        "bootstrap-admin",
        help="空のDBへ最初の管理者と有効化コードを作成します",
    )
    bootstrap_parser.add_argument(
        "--input-json", metavar="PATH", help="UTF-8のJSONから入力します。-は標準入力（--yesが必要）",
    )
    bootstrap_parser.add_argument(
        "--yes", action="store_true", help="確認済みのJSONで作成します。対話入力には使用できません",
    )
    subparsers.add_parser(
        "activate-staff",
        help="既存の職員へローカル認証の有効化コードを発行します",
    )
    args = parser.parse_args(argv)
    if args.command == "bootstrap-admin":
        return bootstrap_admin_command(input_json=args.input_json, yes=args.yes)
    if args.command == "activate-staff":
        return activate_existing_staff_command()
    parser.error("未対応のコマンドです")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
