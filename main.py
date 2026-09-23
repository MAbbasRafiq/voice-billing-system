"""FastAPI entry point for the voice-driven billing system."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database.connection import init_db
from app.routes import billing, catalog, history, settings
from app.services.excel_importer import EXCEL_PATH, import_all_sheets, needs_reimport

load_dotenv()

ROOT = Path(__file__).resolve().parent

app = FastAPI(title="Billing System")

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))

app.include_router(billing.router)
app.include_router(catalog.router)
app.include_router(history.router)
app.include_router(settings.router)


@app.on_event("startup")
def startup():
    init_db()
    (ROOT / "data" / "bills").mkdir(parents=True, exist_ok=True)
    if EXCEL_PATH.exists() and needs_reimport():
        import_all_sheets(force=True)


@app.get("/")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"active": "billing"})


@app.get("/history")
def history_page(request: Request):
    return templates.TemplateResponse(request, "history.html", {"active": "history"})


@app.get("/catalog")
def catalog_page(request: Request):
    return templates.TemplateResponse(request, "catalog.html", {"active": "catalog"})


@app.get("/settings")
def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"active": "settings"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
