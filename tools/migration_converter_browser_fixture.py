"""Synthetic in-memory fixture for migration tests; never accesses the live database."""
from fastapi import Depends
from csrf import CsrfTokenMiddleware, verify_csrf
from routers.data_transfers import router
from tools.spec_change_browser_fixture import app as app

app.add_middleware(CsrfTokenMiddleware)
app.include_router(router, dependencies=[Depends(verify_csrf)])
