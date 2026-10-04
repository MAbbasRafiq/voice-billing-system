"""Catalog-grounded order agent: LLM extract → catalog tools → decide.

No LangGraph. Voice→text stays in the browser (Web Speech API).
This module only handles transcript → cart decisions.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.services.ai_parser import parse_order, pick_catalog_names_batch
from app.services.local_parser import local_parse
from app.services.fuzzy_search import (
    find_catalog_matches,
    fold_part_type_into_query,
    name_matches_discriminators,
    reconcile_item_with_spoken,
    rerank_by_query_tokens,
    canonical_discriminators,
    expand_order_lines,
    content_tokens,
    transcript_matches_catalog,
    normalize_transcript,
    EXACT_TIERS,
    leading_qty_hint,
    qty_before_phrase,
    is_model_only_query,
)


def _prefer_models(matches: list[dict], preferred: Optional[list[str]]) -> list[dict]:
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

    preferred_rows = []
    other_rows = []
    for m in matches:
        if rank(m) < len(prefs):
            preferred_rows.append(m)
        else:
            other_rows.append(m)
    preferred_rows.sort(key=rank)
    return preferred_rows + other_rows


def _looks_like_order(text: str) -> bool:
    """Cheap noise gate before spending an LLM call."""
    t = (text or "").strip()
    if len(t) < 2:
        return False
    # Digits or Urdu/English qty-ish tokens or catalog-ish length
    if re.search(r"\d", t):
        return True
    if re.search(r"[\u0600-\u06FF]", t) and len(t) >= 3:
        return True
    # At least one token with 3+ letters (Latin)
    if re.search(r"[A-Za-z]{3,}", t):
        return True
    # Reject pure punctuation / single syllables
    cleaned = re.sub(r"[\W_]+", "", t, flags=re.UNICODE)
    return len(cleaned) >= 4


def _unique_names(matches: list[dict]) -> set[str]:
    return {(m.get("name") or "").strip().lower() for m in matches if m.get("name")}


def _names_by_score(matches: list[dict]) -> list[str]:
    """Distinct catalog names, best score first (for LLM shortlist)."""
    best: dict[str, float] = {}
    display: dict[str, str] = {}
    for m in matches:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        score = float(m.get("score") or 0)
        if key not in best or score > best[key]:
            best[key] = score
            display[key] = name
    return [display[k] for k, _ in sorted(best.items(), key=lambda kv: -kv[1])]


def _name_scores(matches: list[dict]) -> list[tuple[str, float]]:
    best: dict[str, float] = {}
    display: dict[str, str] = {}
    for m in matches:
        name = (m.get("name") or "").strip()
        if not name:
            continue
        key = name.lower()
        score = float(m.get("score") or 0)
        if key not in best or score > best[key]:
            best[key] = score
            display[key] = name
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    return [(display[k], s) for k, s in ranked]


def _needs_llm_name_pick(matches: list[dict], query: str) -> bool:
    """True only when multiple name families remain after cheap local filters.

    The LLM must never *guess* between families the catalog already matched
    exactly: e.g. "carburetor" matches CARBURETOR (PZ-18), (PZ-22), ... and
    picking one name silently picks one bike model. Those cases go to the user.
    """
    # Exact cascade hits are authoritative: show every variant, let the user choose.
    if matches and all(m.get("match_tier") in EXACT_TIERS for m in matches):
        return False
    narrowed = _narrow_to_best_name(matches, query)
    names = _names_by_score(narrowed)
    if len(names) <= 1:
        return False
    # The request is contained in every candidate name (any length, even one
    # word) → it is generic; keep all variants instead of letting the LLM pick.
    tokens = content_tokens(query)
    if tokens:
        phrase = " ".join(tokens)
        if all(phrase in n.lower() for n in names):
            return False
    ranked = _name_scores(narrowed)
    if len(ranked) >= 2 and ranked[0][1] >= ranked[1][1] + 18:
        # Clear score winner — skip extra LLM call
        return False
    return True


def _filter_matches_to_name(matches: list[dict], picked: Optional[str]) -> list[dict]:
    if not picked:
        return matches
    filtered = [
        m
        for m in matches
        if (m.get("name") or "").strip().lower() == picked.lower()
    ]
    return filtered or matches


def _narrow_to_best_name(matches: list[dict], query: str = "") -> list[dict]:
    """
    Prefer the best-scoring item name, but:
    - Prefer names that contain query discriminators (COMPLETE / LED / LENS / …).
    - Keep sibling names when scores are close.
    """
    if not matches:
        return []

    disc = canonical_discriminators(query)
    pool = matches
    if disc:
        fitted = [
            m
            for m in matches
            if name_matches_discriminators(
                m.get("name") or "", m.get("urdu_name") or "", disc
            )
        ]
        if fitted:
            pool = fitted

    scored = sorted(pool, key=lambda m: float(m.get("score") or 0), reverse=True)
    best = scored[0]
    best_name = (best.get("name") or "").strip().lower()
    best_score = float(best.get("score") or 0)
    same_name = [
        m for m in pool if (m.get("name") or "").strip().lower() == best_name
    ]
    other = [
        m
        for m in scored
        if (m.get("name") or "").strip().lower() != best_name
    ]
    # Wider window so close families stay available for disambiguation
    if other and best_score and float(other[0].get("score") or 0) >= best_score - 15:
        return pool
    return same_name or pool


def _decide_action(line: dict, matches: list[dict], query: str = "") -> str:
    """
    auto_add | disambiguate | ignored

    Never auto-pick when multiple model variants share the same part name.
    """
    if not matches:
        return "ignored"

    narrowed = _narrow_to_best_name(matches, query)
    names = _unique_names(narrowed)

    if len(narrowed) == 1:
        return "auto_add"

    # Same English name, different models → admin must choose
    if len(names) == 1:
        return "disambiguate"

    return "disambiguate"


def _public_match(m: dict) -> dict:
    """Strip internal fields not needed by UI."""
    keys = (
        "id",
        "item_code",
        "model",
        "name",
        "urdu_name",
        "category",
        "cp",
        "ctn_qty",
        "foc_qty",
        "foc_units",
        "qrc_runs",
        "score",
    )
    return {k: m.get(k) for k in keys if k in m or m.get(k) is not None}


def resolve_order(
    text: str,
    preferred_models: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Full agent pipeline for one transcript.

    Returns:
      mode, items (with action + matches), ignored, summary
    """
    text = normalize_transcript((text or "")[:2000])
    preferred_models = preferred_models or []

    # A model by itself is not an order line. Handle this before the local parser
    # (which may otherwise match the model text embedded in one unrelated name)
    # and before the relevance gate (numeric shorthand such as "125").
    if _looks_like_order(text) and is_model_only_query(text):
        return {
            "mode": "local",
            "items": [],
            "ignored": [{"spoken": text, "reason": "model_only"}],
            "summary": {"auto_added": 0, "needs_review": 0, "ignored": 1},
            "message": "That looks like a bike model. Please also enter the part name.",
        }

    if not _looks_like_order(text) or not transcript_matches_catalog(text):
        return {
            "mode": "local",
            "items": [],
            "ignored": [{"spoken": text, "reason": "noise_or_empty"}],
            "summary": {"auto_added": 0, "needs_review": 0, "ignored": 1},
            "message": "Ignored — does not look like a parts order.",
        }

    # Fast path: plain Latin orders whose every segment is an exact catalog hit
    # need no LLM at all (instant, and saves the daily AI quota).
    local_lines = local_parse(text)
    if local_lines:
        parsed = {"results": local_lines, "mode": "local"}
    else:
        parsed = parse_order(text)
    mode = parsed.get("mode") or "fuzzy"
    rescued = False
    if mode in ("groq", "gemini") and not parsed.get("results"):
        # LLMs sometimes answer [] for terse real orders ("ایک باسکٹ", "a dozen basket").
        # The pre-check passed, so ask once more; such lines must then match the
        # catalog exactly (no fuzzy guesses) before we trust them.
        parsed = parse_order(text, force=True)
        mode = parsed.get("mode") or mode
        rescued = bool(parsed.get("results"))
    lines = expand_order_lines(parsed.get("results") or [], text)

    if not lines:
        return {
            "mode": mode,
            "items": [],
            "ignored": [{"spoken": text, "reason": "no_items_extracted"}],
            "summary": {"auto_added": 0, "needs_review": 0, "ignored": 1},
            "message": "No order items found in transcript.",
        }

    items_out: list[dict] = []
    ignored: list[dict] = []
    auto_n = 0
    review_n = 0

    # Pass 1: local catalog match for every line (no per-line LLM)
    prepared: list[dict] = []
    pick_jobs: list[dict] = []
    match_memo: dict[tuple, list[dict]] = {}

    for idx, line in enumerate(lines):
        query = (line.get("item") or line.get("spoken") or "").strip()
        spoken = (line.get("spoken") or query).strip()
        spoken_model = line.get("model")
        query, spoken_model = fold_part_type_into_query(query, spoken_model)
        query = reconcile_item_with_spoken(query, spoken)
        if mode != "local" and len(lines) == 1 and text and text.strip() != spoken:
            query = reconcile_item_with_spoken(query, text)
        qty = int(line.get("qty") or 1)
        # The LLM sometimes drops a clearly spoken quantity ("teen air filter" → 1)
        said = leading_qty_hint(spoken)
        if said is None and qty == 1:
            said = qty_before_phrase(text, spoken)
        if said and said != qty:
            qty = said
        qty = max(1, min(qty, 99999))

        mkey = (query.lower(), (spoken_model or "").lower(), spoken.lower())
        if mkey in match_memo:
            matches = list(match_memo[mkey])
        else:
            matches = find_catalog_matches(query, spoken_model)
            if not matches and spoken and spoken != query:
                matches = find_catalog_matches(
                    reconcile_item_with_spoken(spoken, spoken), spoken_model
                )
            matches = rerank_by_query_tokens(matches, query)
            match_memo[mkey] = list(matches)
        # Fuzzy-only hits (no exact tier) for text unrelated to the catalog = noise
        if matches and not any(m.get("match_tier") for m in matches):
            if rescued or not transcript_matches_catalog(f"{spoken} {query}"):
                matches = []
        matches = _prefer_models(matches, preferred_models)

        row = {
            "line": line,
            "query": query,
            "spoken": spoken,
            "spoken_model": spoken_model,
            "qty": qty,
            "matches": matches,
            "picked_name": None,
        }
        prepared.append(row)

        if matches and _needs_llm_name_pick(matches, query):
            pick_jobs.append(
                {
                    "id": idx,
                    "spoken": spoken or text,
                    "item_hint": query,
                    "candidates": _names_by_score(matches)[:25],
                }
            )

    # Pass 2: at most ONE batched LLM name-pick for all ambiguous lines
    picked_by_id: dict[int, Optional[str]] = {}
    if pick_jobs and mode in ("groq", "gemini"):
        picked_by_id = pick_catalog_names_batch(pick_jobs)

    for idx, row in enumerate(prepared):
        line = row["line"]
        query = row["query"]
        spoken = row["spoken"]
        spoken_model = row["spoken_model"]
        qty = row["qty"]
        matches = row["matches"]

        picked_name = picked_by_id.get(idx)
        llm_narrowed = False
        if picked_name:
            before_names = len(_names_by_score(matches))
            matches = _filter_matches_to_name(matches, picked_name)
            llm_narrowed = before_names > 1
            query = picked_name
        else:
            # Local narrow when we skipped LLM or pick failed
            matches = _narrow_to_best_name(matches, query)
            names = _names_by_score(matches)
            if len(names) == 1:
                query = names[0]

        action = _decide_action(line, matches, query)
        # An LLM guess between several part families is never auto-added:
        # the admin confirms it (mandatory disambiguation).
        if llm_narrowed and action == "auto_add":
            action = "disambiguate"

        confidence = line.get("confidence") or "ambiguous"
        if action == "disambiguate" or len(matches) != 1:
            confidence = "ambiguous"
        if action == "auto_add" and len(matches) == 1:
            confidence = "exact"

        if action == "auto_add" and len(matches) != 1:
            action = "disambiguate"
            confidence = "ambiguous"

        payload = {
            "spoken": spoken,
            "item": query or line.get("item") or spoken,
            "model": spoken_model,
            "qty": qty,
            "confidence": confidence,
            "action": action,
            "matches": [_public_match(m) for m in matches],
        }

        if action == "ignored":
            ignored.append({"spoken": spoken, "reason": "no_catalog_match"})
            continue

        if action == "auto_add":
            auto_n += 1
        else:
            review_n += 1
        items_out.append(payload)

    return {
        "mode": mode,
        "items": items_out,
        "ignored": ignored,
        "summary": {
            "auto_added": auto_n,
            "needs_review": review_n,
            "ignored": len(ignored),
        },
        "message": None,
        "preferred_models": preferred_models,
    }
