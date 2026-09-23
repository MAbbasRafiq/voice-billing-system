"""Settings / import / status routes."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.database.queries import count_items, get_latest_import
from app.services.ai_parser import active_ai_mode
from app.services.excel_importer import EXCEL_PATH, import_all_sheets, needs_reimport

router = APIRouter(prefix="/api")

ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / ".env"


class KeysUpdate(BaseModel):
    groq_api_key: str | None = None
    gemini_api_key: str | None = None
    shop_name: str | None = None


def _mask(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "…" + key[-4:]


@router.get("/status")
def status():
    mode = active_ai_mode()
    latest = get_latest_import()
    return {
        "mode": mode,
        "mode_label": {
            "groq": "AI mode: Groq",
            "gemini": "AI mode: Gemini",
            "fuzzy": "AI unavailable — using manual search mode",
        }.get(mode, mode),
        "item_count": count_items(),
        "excel_exists": EXCEL_PATH.exists(),
        "needs_reimport": needs_reimport() if EXCEL_PATH.exists() else False,
        "last_import": latest,
        "shop_name": os.getenv("SHOP_NAME", "Spare Parts Shop"),
        "keys": {
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "gemini": bool(os.getenv("GEMINI_API_KEY")),
            "groq_masked": _mask(os.getenv("GROQ_API_KEY")),
            "gemini_masked": _mask(os.getenv("GEMINI_API_KEY")),
        },
        "models": {
            "groq": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
            "gemini": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        },
    }


@router.post("/import")
def import_excel(force: bool = True):
    summary = import_all_sheets(force=force)
    return summary


def _upsert_env(updates: dict[str, str]) -> None:
    existing: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
    for k, v in updates.items():
        if v is not None:
            existing[k] = v
    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # refresh process env
    for k, v in updates.items():
        if v is not None:
            os.environ[k] = v


@router.post("/settings/keys")
def update_keys(payload: KeysUpdate):
    updates = {}
    if payload.groq_api_key is not None:
        updates["GROQ_API_KEY"] = payload.groq_api_key.strip()
    if payload.gemini_api_key is not None:
        updates["GEMINI_API_KEY"] = payload.gemini_api_key.strip()
    if payload.shop_name is not None:
        updates["SHOP_NAME"] = payload.shop_name.strip() or "Spare Parts Shop"
    if updates:
        _upsert_env(updates)
    return status()
