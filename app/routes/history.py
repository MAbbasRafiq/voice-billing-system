"""Bill history routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.database.queries import get_bill, list_bills

router = APIRouter(prefix="/api")


@router.get("/history")
def history(limit: int = 100):
    return {"bills": list_bills(limit=limit)}


@router.get("/bills/{bill_id}")
def bill_detail(bill_id: int):
    bill = get_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill
