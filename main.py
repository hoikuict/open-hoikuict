from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from database import create_db_and_tables, seed_sample_data
from routers.children import router as children_router

app = FastAPI(title="open-hoikuict", version="0.1.0")
app.include_router(children_router)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()
    seed_sample_data()


@app.get("/")
def root():
    return RedirectResponse(url="/children")
