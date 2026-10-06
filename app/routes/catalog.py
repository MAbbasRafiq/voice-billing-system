"""Catalog browse and search routes."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.database.queries import (
    catalog_items,
    count_catalog_items,
    get_items_by_exact_name,
    list_categories,
)
from app.services.fuzzy_search import browse_catalog_hybrid, search_catalog

router = APIRouter(prefix="/api")


@router.get("/catalog")
def catalog(
    q: Optional[str] = None,
    category: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    query = (q or "").strip()
    if query:
        # Strong prefix/relevance hits first; remaining SQL LIKE hits appended.
        items, total = browse_catalog_hybrid(
            query,
            category=category,
            preferred_model=model,
            limit=limit,
            offset=offset,
        )
    else:
        items = catalog_items(
            q=None, category=category, model=model, limit=limit, offset=offset
        )
        total = count_catalog_items(q=None, category=category, model=model)
    return {
        "items": items,
        "categories": list_categories(),
        "count": len(items),
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=100),
    model: Optional[str] = None,
    models: Optional[str] = None,
):
    preferred_models = None
    if models:
        preferred_models = [p.strip() for p in models.split(",") if p.strip()]
    return {
        "items": search_catalog(
            q,
            limit=limit,
            preferred_model=model,
            preferred_models=preferred_models,
        )
    }


@router.get("/catalog/by-name")
def catalog_by_name(
    name: str = Query(..., min_length=1),
    limit: int = Query(200, ge=1, le=500),
):
    """All model variants for one catalog English name family."""
    items = get_items_by_exact_name(name.strip(), limit=limit)
    return {"name": name.strip(), "items": items, "count": len(items)}
