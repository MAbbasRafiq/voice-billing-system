"""RapidFuzz offline order parsing and catalog ranking."""

from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz, process

from app.database.queries import get_all_items_for_fuzzy


def _build_choices(items: list[dict]) -> tuple[list[str], list[dict]]:
    labels = []
    mapped = []
    for item in items:
        name = (item.get("name") or "").strip()
        urdu = (item.get("urdu_name") or "").strip()
        code = (item.get("item_code") or "").strip()
        model = (item.get("model") or "").strip()
        for label in filter(None, [name, urdu, f"{name} {model}".strip(), code]):
            labels.append(label)
            mapped.append(item)
    return labels, mapped


def rank_catalog(q: str, limit: int = 30) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    items = get_all_items_for_fuzzy()
    if not items:
        return []
    labels, mapped = _build_choices(items)
    hits = process.extract(q, labels, scorer=fuzz.WRatio, limit=limit * 3)
    seen = set()
    results = []
    for _label, score, idx in hits:
        item = mapped[idx]
        if item["id"] in seen or score < 45:
            continue
        seen.add(item["id"])
        row = dict(item)
        row["score"] = score
        results.append(row)
        if len(results) >= limit:
            break
    return results


def _extract_qty_phrases(text: str) -> list[tuple[int, str]]:
    """
    Pull (qty, phrase) pairs from spoken order text.
    Falls back to whole text with qty=1.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    # Split on common separators
    chunks = re.split(r"\band\b|,|;|\n", text, flags=re.IGNORECASE)
    results = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^(\d+)\s*[xX]?\s+(.+)$", chunk)
        if m:
            results.append((int(m.group(1)), m.group(2).strip()))
            continue
        m = re.search(r"(.+?)\s+(\d+)\s*(?:pcs?|pieces?|qty)?$", chunk, re.IGNORECASE)
        if m and len(m.group(1).strip()) > 2:
            results.append((int(m.group(2)), m.group(1).strip()))
            continue
        results.append((1, chunk))
    return results if results else [(1, text)]


def _guess_model(phrase: str) -> Optional[str]:
    # Common model tokens in this catalog
    patterns = [
        r"\bCD70[-\s]?EURO2\b",
        r"\bCD70F\b",
        r"\bCD70[-\s]?CDI\b",
        r"\bCD70\b",
        r"\bCG125\b",
        r"\bFIT\s?150\b",
        r"\bPRID[EA]\b",
    ]
    for pat in patterns:
        m = re.search(pat, phrase, re.IGNORECASE)
        if m:
            return m.group(0).upper().replace(" ", "")
    return None


def fuzzy_parse_order(text: str) -> list[dict]:
    """
    Offline fallback: split order into phrases and fuzzy-match item names.
    Always prefers ambiguous when multiple catalog hits exist.
    """
    items = get_all_items_for_fuzzy()
    labels, mapped = _build_choices(items) if items else ([], [])
    parsed = []

    for qty, phrase in _extract_qty_phrases(text):
        model = _guess_model(phrase)
        clean = phrase
        if model:
            clean = re.sub(re.escape(model), "", clean, flags=re.IGNORECASE)
            clean = re.sub(r"\bfor\b|\bof\b", "", clean, flags=re.IGNORECASE).strip(" -")

        spoken = phrase
        if not labels:
            parsed.append(
                {
                    "spoken": spoken,
                    "item": clean or phrase,
                    "model": model,
                    "qty": qty,
                    "confidence": "ambiguous",
                }
            )
            continue

        hits = process.extract(clean or phrase, labels, scorer=fuzz.WRatio, limit=5)
        best_label, best_score, best_idx = hits[0]
        best_item = mapped[best_idx]
        item_name = best_item.get("name") or clean or phrase

        # Count unique item names near the top score
        near = [
            mapped[i]
            for _l, s, i in hits
            if s >= max(50, best_score - 8)
        ]
        unique_names = { (x.get("name") or "").lower() for x in near }

        confidence = "exact" if best_score >= 88 and len(unique_names) == 1 and model else "ambiguous"
        if best_score < 55:
            confidence = "ambiguous"
            item_name = clean or phrase

        parsed.append(
            {
                "spoken": spoken,
                "item": item_name,
                "model": model,
                "qty": qty,
                "confidence": confidence,
            }
        )

    return parsed
