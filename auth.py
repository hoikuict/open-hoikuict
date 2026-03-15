from enum import Enum
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request
from starlette.responses import RedirectResponse


class Role(str, Enum):
    VIEW_ONLY = "view_only"
    CAN_EDIT = "can_edit"
    ADMIN = "admin"


ROLE_LABELS = {
    Role.VIEW_ONLY: "閲覧のみ",
    Role.CAN_EDIT: "編集可",
    Role.ADMIN: "管理者",
}


class MockUser:
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


MOCK_ROLE_COOKIE = "mock_role"
MOCK_PARENT_ACCOUNT_COOKIE = "mock_parent_account_id"


def get_mock_current_user(request: Request) -> MockUser:
    role = Role.CAN_EDIT
    as_param = request.query_params.get("as")
    if as_param and as_param in [item.value for item in Role]:
        role = Role(as_param)
    else:
        cookie_role = request.cookies.get(MOCK_ROLE_COOKIE)
        if cookie_role and cookie_role in [item.value for item in Role]:
            role = Role(cookie_role)
    return MockUser(role=role)


def get_mock_parent_account_id(request: Request) -> Optional[int]:
    raw_id = request.cookies.get(MOCK_PARENT_ACCOUNT_COOKIE)
    if not raw_id:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def set_mock_parent_cookie(response: RedirectResponse, parent_account_id: int) -> None:
    response.set_cookie(MOCK_PARENT_ACCOUNT_COOKIE, str(parent_account_id), max_age=60 * 60 * 24)


def clear_mock_parent_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(MOCK_PARENT_ACCOUNT_COOKIE)


CurrentUser = Annotated[MockUser, Depends(get_mock_current_user)]


def require_can_edit(user: CurrentUser) -> None:
    if not user.can_edit:
        raise HTTPException(status_code=403, detail="編集の権限がありません")


def require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
