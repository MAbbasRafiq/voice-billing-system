"""FastAPI entry point for the voice-driven billing system."""

from __future__ import annotations

import os
import threading
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


@app.middleware("http")
async def _static_revalidate(request: Request, call_next):
    """Make browsers revalidate JS/CSS on every load (cheap 304 via ETag), so an
    updated billing.js is picked up immediately instead of a stale cached copy."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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
    threading.Thread(target=_warm_up, daemon=True).start()


def _warm_up() -> None:
    """Pre-build catalog indexes and open the LLM connection so the first order is fast."""
    try:
        from app.services.fuzzy_search import find_catalog_matches, transcript_matches_catalog

        transcript_matches_catalog("warm up")
        find_catalog_matches("air filter")
    except Exception:
        pass
    try:
        from app.services.ai_parser import warm_up_llm

        warm_up_llm()
    except Exception:
        pass
    try:
        from app.services.speech_to_text import warm_up_stt

        warm_up_stt()
    except Exception:
        pass


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
