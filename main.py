from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from database import create_db_and_tables, seed_sample_data
from routers.children import router as children_router
from auth import Role, MOCK_ROLE_COOKIE

app = FastAPI(title="open-hoikuict", version="0.1.0")
app.include_router(children_router)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_sample_data()


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
