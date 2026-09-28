"""Billing routes: parse-order, bill create/download."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.database.queries import (
    create_bill,
    get_bill,
    get_item_by_id,
    update_bill_pdf,
)
from app.services.ai_parser import parse_order
from app.services.foc_calculator import calculate_foc
from app.services.fuzzy_search import find_catalog_matches
from app.services.pdf_generator import generate_bill_pdf

router = APIRouter(prefix="/api")


class OrderRequest(BaseModel):
    text: str
    preferred_model: Optional[str] = None  # legacy single
    preferred_models: Optional[list[str]] = None


def _prefer_models(matches: list[dict], preferred: Optional[list[str]]) -> list[dict]:
    """Sort matches so preferred model variants appear first — never drop others."""
    if not preferred or not matches:
        return matches
    prefs = [p.strip().lower() for p in preferred if p and str(p).strip()]
    if not prefs:
        return matches

    def rank(m: dict) -> int:
        model = (m.get("model") or "").lower()
        for i, p in enumerate(prefs):
            if p in model or model in p:
                return i
        return len(prefs)

    # Stable-ish: preferred first (by preference order), then the rest in original order
    preferred_rows = []
    other_rows = []
    for m in matches:
        if rank(m) < len(prefs):
            preferred_rows.append(m)
        else:
            other_rows.append(m)
    preferred_rows.sort(key=rank)
    return preferred_rows + other_rows


@router.post("/parse-order")
def parse_order_route(req: OrderRequest):
    from app.services.fuzzy_search import _has_arabic_script, fuzzy_parse_order

    # Urdu-script orders: LLMs often mistranslate part names (لوٹا→filter).
    # Use offline fuzzy against English + urdu_name for phrase extraction.
    if _has_arabic_script(req.text):
        result = {"results": fuzzy_parse_order(req.text), "mode": "fuzzy"}
    else:
        result = parse_order(req.text)

    preferred: list[str] = []
    if req.preferred_models:
        preferred.extend([p for p in req.preferred_models if p and str(p).strip()])
    if req.preferred_model and req.preferred_model.strip():
        preferred.append(req.preferred_model.strip())
    # de-dupe case-insensitive, keep order
    seen = set()
    preferred_unique = []
    for p in preferred:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            preferred_unique.append(p)

    enriched = []
    for item in result["results"]:
        spoken_model = item.get("model")
        # Prefer spoken item text; also try spoken phrase for Urdu full utterances
        query = item.get("item") or item.get("spoken") or ""
        matches = find_catalog_matches(query, spoken_model)
        if not matches and item.get("spoken") and item.get("spoken") != query:
            matches = find_catalog_matches(item.get("spoken") or "", spoken_model)
        matches = _prefer_models(matches, preferred_unique)
        confidence = item.get("confidence") or "ambiguous"
        if len(matches) != 1:
            confidence = "ambiguous"
        enriched.append({**item, "confidence": confidence, "matches": matches})
    return {
        "mode": result["mode"],
        "items": enriched,
        "preferred_models": preferred_unique,
    }


class BillLineIn(BaseModel):
    item_id: int
    qty: int = Field(ge=1)
    unit_price: Optional[float] = None


class BillRequest(BaseModel):
    customer: Optional[str] = ""
    lines: list[BillLineIn]


def _build_bill_lines(payload_lines: list[BillLineIn]) -> tuple[list[dict], float]:
    expanded: list[dict] = []
    total = 0.0
    for line in payload_lines:
        item = get_item_by_id(line.item_id)
        if not item:
            raise HTTPException(status_code=400, detail=f"Unknown item_id {line.item_id}")
        cp = float(line.unit_price) if line.unit_price is not None else float(item["cp"])
        foc_lines = calculate_foc(cp, line.qty, item.get("foc_qty"), item.get("foc_units"))
        for fl in foc_lines:
            row = {
                "item_id": item["id"],
                "item_code": item.get("item_code"),
                "model": item.get("model"),
                "name": item.get("name"),
                "qty": fl["qty"],
                "unit_price": fl["unit_price"],
                "line_total": fl["line_total"],
                "is_foc": fl["is_foc"],
            }
            expanded.append(row)
            total += float(fl["line_total"])
    return expanded, round(total, 2)


@router.post("/bill/preview")
def preview_bill(payload: BillRequest):
    """Compute FOC lines and totals without saving."""
    lines, total = _build_bill_lines(payload.lines)
    return {"customer": payload.customer or "", "lines": lines, "total": total}


@router.post("/bill")
def create_bill_route(payload: BillRequest):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Bill has no lines")
    lines, total = _build_bill_lines(payload.lines)
    bill_id = create_bill(payload.customer, total, "", lines)
    bill = get_bill(bill_id)
    pdf_path = generate_bill_pdf(
        bill_id=bill_id,
        customer=payload.customer,
        created_at=bill.get("created_at") if bill else None,
        lines=lines,
        total=total,
        shop_name=os.getenv("SHOP_NAME", "Spare Parts Shop"),
    )
    update_bill_pdf(bill_id, pdf_path)
    return {
        "id": bill_id,
        "total": total,
        "pdf_url": f"/api/bill/{bill_id}/pdf",
        "lines": lines,
    }


@router.get("/bill/{bill_id}")
def get_bill_route(bill_id: int):
    bill = get_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


@router.get("/bill/{bill_id}/pdf")
def download_pdf(bill_id: int):
    bill = get_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    pdf_path = bill.get("pdf_path")
    if not pdf_path or not os.path.isfile(pdf_path):
        # regenerate if missing
        lines = bill.get("items") or []
        pdf_path = generate_bill_pdf(
            bill_id=bill_id,
            customer=bill.get("customer"),
            created_at=bill.get("created_at"),
            lines=lines,
            total=float(bill.get("total") or 0),
        )
        update_bill_pdf(bill_id, pdf_path)
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"bill_{bill_id}.pdf",
    )
