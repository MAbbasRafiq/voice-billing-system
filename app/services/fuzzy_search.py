"""RapidFuzz offline order parsing and catalog ranking."""

from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz, process

from app.database.queries import get_all_items_for_fuzzy, search_items_by_name

# Common spoken quantity words (Urdu) → number
URDU_QTY_WORDS = {
    "ایک": 1,
    "دو": 2,
    "تین": 3,
    "چار": 4,
    "پانچ": 5,
    "پنج": 5,
    "چھ": 6,
    "چھے": 6,
    "سات": 7,
    "آٹھ": 8,
    "اٹھ": 8,
    "نو": 9,
    "دس": 10,
    "بیس": 20,
    "پچاس": 50,
}


def _has_arabic_script(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def strip_leading_qty(text: str) -> tuple[int, str]:
    """
    Pull leading qty (digits or Urdu number word) from a phrase.
    Returns (qty, remainder). Default qty=1.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return 1, ""

    m = re.match(r"^(\d+)\s*[xX]?\s*(.+)$", text)
    if m:
        return max(1, int(m.group(1))), m.group(2).strip()

    parts = text.split(" ", 1)
    if parts and parts[0] in URDU_QTY_WORDS:
        rest = parts[1].strip() if len(parts) > 1 else ""
        return URDU_QTY_WORDS[parts[0]], rest

    return 1, text


def clean_item_query(text: str) -> str:
    """Remove leading qty words so Urdu/English search hits the part name."""
    _qty, rest = strip_leading_qty(text)
    return (rest or text or "").strip()


def find_catalog_matches(
    item_query: str,
    model: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Resolve spoken/typed item text to catalog rows.
    Tries SQL LIKE first, then RapidFuzz (needed for Urdu spelling variants
    e.g. sheet ائیر لوٹا vs spoken ایئر لوٹا).
    """
    q = clean_item_query(item_query)
    if not q:
        return []

    like_matches = search_items_by_name(q, model, limit=limit)
    if not like_matches and model:
        like_matches = search_items_by_name(q, None, limit=limit)

    if like_matches and not _has_arabic_script(q):
        return like_matches[:limit]

    fuzzy = rank_catalog(q, limit=max(limit, 40), preferred_model=model)
    if not fuzzy and model:
        fuzzy = rank_catalog(q, limit=max(limit, 40))

    # Keep only strong fuzzy hits (Urdu spellings vary; avoid weak noise)
    if fuzzy:
        best = float(fuzzy[0].get("score") or 0)
        min_score = 70 if _has_arabic_script(q) else 55
        fuzzy = [
            r
            for r in fuzzy
            if float(r.get("score") or 0) >= max(min_score, best - 10)
        ]

    if not like_matches:
        return fuzzy[:limit]

    seen = {m["id"] for m in like_matches}
    merged = list(like_matches)
    for row in fuzzy:
        if row["id"] not in seen:
            merged.append(row)
            seen.add(row["id"])
    return merged[:limit]


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


def rank_catalog(
    q: str,
    limit: int = 30,
    preferred_model: Optional[str] = None,
    preferred_models: Optional[list] = None,
) -> list[dict]:
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
        if len(results) >= limit * 2:
            break

    prefs: list[str] = []
    if preferred_models:
        prefs.extend([str(p).strip().lower() for p in preferred_models if p and str(p).strip()])
    if preferred_model and preferred_model.strip():
        prefs.append(preferred_model.strip().lower())
    # de-dupe
    seen_p = set()
    prefs_u = []
    for p in prefs:
        if p not in seen_p:
            seen_p.add(p)
            prefs_u.append(p)

    if prefs_u:
        def rank(r):
            model = (r.get("model") or "").lower()
            for i, p in enumerate(prefs_u):
                if p in model or model in p:
                    return i
            return len(prefs_u)

        yes = [r for r in results if rank(r) < len(prefs_u)]
        no = [r for r in results if rank(r) >= len(prefs_u)]
        yes.sort(key=rank)
        results = yes + no
    return results[:limit]


def _extract_qty_phrases(text: str) -> list[tuple[int, str]]:
    """
    Pull (qty, phrase) pairs from spoken order text.
    Supports leading digits and Urdu quantity words (دو، تین، …).
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    # Split on common separators (English + Urdu "اور")
    chunks = re.split(r"\band\b|اور|,|;|\n", text, flags=re.IGNORECASE)
    results = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        qty, rest = strip_leading_qty(chunk)
        if rest:
            results.append((qty, rest))
        else:
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
        # Prefer English catalog name for downstream search/display
        item_name = best_item.get("name") or clean or phrase

        # Count unique item names near the top score
        near = [
            mapped[i]
            for _l, s, i in hits
            if s >= max(50, best_score - 8)
        ]
        unique_names = {(x.get("name") or "").lower() for x in near}

        confidence = "exact" if best_score >= 88 and len(unique_names) == 1 and model else "ambiguous"
        if best_score < 55:
            confidence = "ambiguous"
            # Keep original (possibly Urdu) text — enrichment will fuzzy-match urdu_name
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
