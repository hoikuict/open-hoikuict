from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from auth import MOCK_ROLE_COOKIE, Role
from database import (
    bootstrap_family_records,
    create_db_and_tables,
    seed_classroom_data,
    seed_parent_portal_data,
    seed_sample_data,
)
from routers.attendance import router as attendance_router
from routers.attendance_checks import router as attendance_checks_router
from routers.child_change_requests import router as child_change_requests_router
from routers.children import router as children_router
from routers.classrooms import router as classrooms_router
from routers.daily_contacts import router as daily_contacts_router
from routers.families import router as families_router
from routers.guardian import router as guardian_router
from routers.meeting_notes import router as meeting_notes_router
from routers.notices import router as notices_router
from routers.parent_accounts import router as parent_accounts_router
from routers.parent_portal import router as parent_portal_router
from routers.staff_auth import router as staff_auth_router
from routers.staff_rooms import router as staff_rooms_router

app = FastAPI(title="open-hoikuict", version="0.1.0")
app.include_router(classrooms_router)
app.include_router(families_router)
app.include_router(children_router)
app.include_router(child_change_requests_router)
app.include_router(attendance_router)
app.include_router(attendance_checks_router)
app.include_router(guardian_router)
app.include_router(parent_accounts_router)
app.include_router(parent_portal_router)
app.include_router(staff_auth_router)
app.include_router(meeting_notes_router)
app.include_router(notices_router)
app.include_router(daily_contacts_router)
app.include_router(staff_rooms_router)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_classroom_data()
    seed_sample_data()
    bootstrap_family_records()
    seed_parent_portal_data()


@app.get("/")
def root():
    return RedirectResponse(url="/children")


@app.get("/switch-role")
def switch_role(request: Request, role: str = "can_edit", redirect: str = "/children/"):
    """
    モック用：権限レベルを切り替える。
    role: view_only | can_edit | admin
    """
    if role in [r.value for r in Role]:
        response = RedirectResponse(url=redirect, status_code=303)
        response.set_cookie(MOCK_ROLE_COOKIE, role, max_age=60 * 60 * 24)  # 24時間
        return response
    return RedirectResponse(url=redirect, status_code=303)
