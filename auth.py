"""
職員の管理レベル（モック）
※ 認証は未実装。実装後は本モジュールを差し替える。
"""
from enum import Enum
from typing import Annotated

from fastapi import Depends, Request, HTTPException
from starlette.responses import RedirectResponse


class Role(str, Enum):
    """職員の権限レベル"""
    VIEW_ONLY = "view_only"   # 閲覧のみ
    CAN_EDIT = "can_edit"     # 編集可
    ADMIN = "admin"           # 管理者（将来用）


ROLE_LABELS = {
    Role.VIEW_ONLY: "閲覧のみ",
    Role.CAN_EDIT: "編集可",
    Role.ADMIN: "管理者",
}


class MockUser:
    """モックユーザー（認証実装後に差し替え）"""
    def __init__(self, role: Role, name: str = "職員"):
        self.role = role
        self.name = name

    @property
    def can_view(self) -> bool:
        return True

    @property
    def can_edit(self) -> bool:
        return self.role in (Role.CAN_EDIT, Role.ADMIN)

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role.value)


# Cookie名（モック用）
MOCK_ROLE_COOKIE = "mock_role"


def get_mock_current_user(request: Request) -> MockUser:
    """
    現在のユーザーを取得（モック）
    クエリ ?as=view_only / ?as=can_edit / ?as=admin または cookie で制御。
    デフォルトは編集可。
    """
    role = Role.CAN_EDIT  # デフォルト

    # クエリパラメータ優先（テスト用）
    as_param = request.query_params.get("as")
    if as_param and as_param in [r.value for r in Role]:
        role = Role(as_param)
    else:
        # Cookieから取得
        cookie_role = request.cookies.get(MOCK_ROLE_COOKIE)
        if cookie_role and cookie_role in [r.value for r in Role]:
            role = Role(cookie_role)

    return MockUser(role=role)


# 型エイリアス（Dependsで使用）
CurrentUser = Annotated[MockUser, Depends(get_mock_current_user)]


def require_can_edit(user: CurrentUser) -> None:
    """編集権限がない場合に403を送出"""
    if not user.can_edit:
        raise HTTPException(status_code=403, detail="編集の権限がありません")
