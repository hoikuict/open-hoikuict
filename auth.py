from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Optional, Protocol

from fastapi import Depends, HTTPException, Request, Response


class Role(str, Enum):
    VIEW_ONLY = "view_only"
    CAN_EDIT = "can_edit"
    ADMIN = "admin"


ROLE_LABELS = {
    Role.VIEW_ONLY: "閲覧のみ",
    Role.CAN_EDIT: "編集可能",
    Role.ADMIN: "管理者",
}

MOCK_ROLE_COOKIE = "mock_role"
MOCK_PARENT_ACCOUNT_COOKIE = "mock_parent_account_id"


@dataclass(slots=True)
class StaffUser:
    role: Role
    name: str = "管理者"

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


class StaffAuthBackend(Protocol):
    def get_current_user(self, request: Request) -> StaffUser: ...


class ParentPortalAuthBackend(Protocol):
    def get_parent_account_id(self, request: Request) -> Optional[int]: ...

    def set_parent_session(self, response: Response, parent_account_id: int) -> None: ...

    def clear_parent_session(self, response: Response) -> None: ...


class MockStaffAuthBackend:
    def get_current_user(self, request: Request) -> StaffUser:
        role = Role.CAN_EDIT
        as_param = request.query_params.get("as")
        valid_roles = {item.value for item in Role}
        if as_param and as_param in valid_roles:
            role = Role(as_param)
        else:
            cookie_role = request.cookies.get(MOCK_ROLE_COOKIE)
            if cookie_role and cookie_role in valid_roles:
                role = Role(cookie_role)
        return StaffUser(role=role)


class MockParentPortalAuthBackend:
    def get_parent_account_id(self, request: Request) -> Optional[int]:
        raw_id = request.cookies.get(MOCK_PARENT_ACCOUNT_COOKIE)
        if not raw_id:
            return None
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return None

    def set_parent_session(self, response: Response, parent_account_id: int) -> None:
        response.set_cookie(MOCK_PARENT_ACCOUNT_COOKIE, str(parent_account_id), max_age=60 * 60 * 24)

    def clear_parent_session(self, response: Response) -> None:
        response.delete_cookie(MOCK_PARENT_ACCOUNT_COOKIE)


_staff_auth_backend: StaffAuthBackend = MockStaffAuthBackend()
_parent_portal_auth_backend: ParentPortalAuthBackend = MockParentPortalAuthBackend()


def configure_staff_auth_backend(backend: StaffAuthBackend) -> None:
    global _staff_auth_backend
    _staff_auth_backend = backend


def configure_parent_portal_auth_backend(backend: ParentPortalAuthBackend) -> None:
    global _parent_portal_auth_backend
    _parent_portal_auth_backend = backend


def reset_auth_backends() -> None:
    configure_staff_auth_backend(MockStaffAuthBackend())
    configure_parent_portal_auth_backend(MockParentPortalAuthBackend())


def get_current_staff_user(request: Request) -> StaffUser:
    return _staff_auth_backend.get_current_user(request)


def get_current_parent_account_id(request: Request) -> Optional[int]:
    return _parent_portal_auth_backend.get_parent_account_id(request)


def set_parent_account_cookie(response: Response, parent_account_id: int) -> None:
    _parent_portal_auth_backend.set_parent_session(response, parent_account_id)


def clear_parent_account_cookie(response: Response) -> None:
    _parent_portal_auth_backend.clear_parent_session(response)


# Compatibility aliases for the current mock-based code path.
MockUser = StaffUser
get_mock_current_user = get_current_staff_user
get_mock_parent_account_id = get_current_parent_account_id
set_mock_parent_cookie = set_parent_account_cookie
clear_mock_parent_cookie = clear_parent_account_cookie

CurrentUser = Annotated[StaffUser, Depends(get_current_staff_user)]


def require_can_edit(user: CurrentUser) -> None:
    if not user.can_edit:
        raise HTTPException(status_code=403, detail="編集権限がありません")


def require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
