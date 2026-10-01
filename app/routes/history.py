"""Bill history routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.database.queries import (
    bills_today_summary,
    get_bill,
    get_latest_bill_id,
    list_bills,
    list_recent_customers,
)

router = APIRouter(prefix="/api")


@router.get("/history")
def history(limit: int = 100):
    today = bills_today_summary()
    return {
        "bills": list_bills(limit=limit),
        "today": today,
    }


@router.get("/customers/recent")
def recent_customers(limit: int = 25):
    return {"customers": list_recent_customers(limit=limit)}


@router.get("/bills/latest")
def latest_bill():
    bill_id = get_latest_bill_id()
    if not bill_id:
        raise HTTPException(status_code=404, detail="No bills yet")
    bill = get_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="No bills yet")
    return bill


@router.get("/bills/{bill_id}")
def bill_detail(bill_id: int):
    bill = get_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill
