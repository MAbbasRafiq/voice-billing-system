"""Catalog browse and search routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.database.queries import catalog_items, list_categories
from app.services.fuzzy_search import rank_catalog

router = APIRouter(prefix="/api")


@router.get("/catalog")
def catalog(
    q: Optional[str] = None,
    category: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    items = catalog_items(q=q, category=category, model=model, limit=limit, offset=offset)
    return {
        "items": items,
        "categories": list_categories(),
        "count": len(items),
    }


@router.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(30, ge=1, le=100)):
    return {"items": rank_catalog(q, limit=limit)}
