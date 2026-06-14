from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from database import (
    bootstrap_health_records,
    bootstrap_family_records,
    create_db_and_tables,
    seed_calendar_data,
    seed_classroom_data,
    seed_extended_care_fee_rules,
    seed_parent_portal_data,
    seed_sample_data,
)
from routers.attendance import router as attendance_router
from routers.attendance_checks import router as attendance_checks_router
from routers.billing import router as billing_router
from routers.calendar import router as calendar_router
from routers.child_change_requests import router as child_change_requests_router
from routers.children import router as children_router
from routers.child_health import router as child_health_router
from routers.classrooms import router as classrooms_router
from routers.data_transfers import router as data_transfers_router
from routers.daily_contacts import router as daily_contacts_router
from routers.extended_care_fees import router as extended_care_fees_router
from routers.families import router as families_router
from routers.guardian import router as guardian_router
from routers.meeting_notes import router as meeting_notes_router
from routers.notices import router as notices_router
from routers.parent_accounts import router as parent_accounts_router
from routers.parent_portal import router as parent_portal_router
from routers.staff_auth import router as staff_auth_router
from routers.staff_rooms import router as staff_rooms_router
from routers.staff_surveys import router as staff_surveys_router
from routers.surveys import router as surveys_router
from routers.zengin import router as zengin_router
from plan_docs.runtime import ensure_runtime_files
from plan_docs.routers.bunrei import router as plan_docs_bunrei_router
from plan_docs.routers.documents import router as plan_docs_documents_router
from plan_docs.routers.home import router as plan_docs_home_router
from plan_docs.routers.plans import router as plan_docs_plans_router


def initialize_application() -> None:
    ensure_runtime_files()
    create_db_and_tables()
    seed_classroom_data()
    seed_extended_care_fee_rules()
    seed_sample_data()
    bootstrap_family_records()
    bootstrap_health_records()
    seed_parent_portal_data()
    seed_calendar_data()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_application()
    yield


app = FastAPI(title="open-hoikuict", version="0.1.0", lifespan=lifespan)
app.include_router(classrooms_router)
app.include_router(data_transfers_router)
app.include_router(families_router)
app.include_router(children_router)
app.include_router(child_health_router)
app.include_router(child_change_requests_router)
app.include_router(attendance_router)
app.include_router(attendance_checks_router)
app.include_router(extended_care_fees_router)
app.include_router(billing_router)
app.include_router(guardian_router)
app.include_router(parent_accounts_router)
app.include_router(parent_portal_router)
app.include_router(calendar_router)
app.include_router(staff_auth_router)
app.include_router(meeting_notes_router)
app.include_router(notices_router)
app.include_router(daily_contacts_router)
app.include_router(staff_rooms_router)
app.include_router(surveys_router)
app.include_router(staff_surveys_router)
app.include_router(zengin_router)
app.include_router(plan_docs_home_router, prefix="/plans")
app.include_router(plan_docs_plans_router, prefix="/plans")
app.include_router(plan_docs_documents_router, prefix="/plans")
app.include_router(plan_docs_bunrei_router, prefix="/plans")

@app.get("/")
def root():
    return RedirectResponse(url="/children")


@app.get("/switch-role")
def switch_role(redirect: str = "/children"):
    target = redirect if redirect.startswith("/") and not redirect.startswith("//") else "/children"
    return RedirectResponse(url=f"/staff/login?redirect={target}", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
