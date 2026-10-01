"""Instant, LLM-free parsing for plain Latin-script orders.

Most typed / English-dictated orders look like "2 back light complete, 5 chain kit".
For those, the catalog itself is the authority: if EVERY segment resolves to an exact
catalog hit (code / exact name / phrase / all-words) we can skip the LLM entirely —
no latency, no quota. Anything uncertain (Urdu script, typos, trailing quantities,
unknown words, ...) returns None and the caller falls back to the LLM.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.fuzzy_search import (
    TIER_CODE,
    TIER_EXACT,
    TIER_PHRASE,
    LATIN_QTY_WORDS,
    TIER_WORDS,
    _has_arabic_script,
    catalog_vocab,
    find_catalog_matches,
)

_TRUSTED_TIERS = {TIER_CODE, TIER_EXACT, TIER_PHRASE, TIER_WORDS}

_NUM_WORDS = LATIN_QTY_WORDS

_SEPARATORS = re.compile(r"\s*(?:,|;|\+|&|\band\b|\baur\b|\bplus\b|\balso\b|\bthen\b)\s*", re.I)
_LEAD_FILLER = re.compile(
    r"^(?:please|pls|give me|give|i need|i want|need|want|add|also|and)\s+", re.I
)
# Leading quantity: "5", "5x", "5 x", "two", "a dozen", "half dozen"
_LEAD_QTY = re.compile(
    r"^(?:(?P<num>\d{1,5})\s*(?:x(?=\s|$))?|(?P<half>half\s+dozen)|(?P<adozen>a\s+dozen)"
    r"|(?P<word>[a-z]+)(?=\s))\s*",
    re.I,
)
# Interior "<qty> <item>" boundary inside a segment (digits only, to stay conservative)
_INTERIOR_QTY = re.compile(r"(?<=\D)\s+(\d{1,3})\s+(?=[A-Za-z])")


def _split_segments(text: str) -> list[str]:
    parts = [p.strip() for p in _SEPARATORS.split(text) if p and p.strip()]
    out: list[str] = []
    for p in parts:
        # "2 back light complete 1 back light led" (no separator): split before a digit
        # that is followed by letters and preceded by a word.
        pieces = re.split(_INTERIOR_QTY, p)
        if len(pieces) == 1:
            out.append(p)
            continue
        # re.split with a capture group returns [text, qty, text, qty, ...]
        head = pieces[0].strip()
        probe = head
        for _ in range(3):
            probe = _LEAD_FILLER.sub("", probe + " ").strip()
        if probe:  # "please give me 3 basket" → head is only filler, drop it
            out.append(head)
        for i in range(1, len(pieces), 2):
            out.append(f"{pieces[i]} {pieces[i + 1].strip()}")
    return [s for s in out if s]


def _take_qty(segment: str) -> Optional[tuple[int, str, Optional[str]]]:
    """(qty, item text, the single qty word used or None)."""
    seg = segment.strip()
    for _ in range(3):  # "please give me 3 basket"
        stripped = _LEAD_FILLER.sub("", seg)
        if stripped == seg:
            break
        seg = stripped
    word_used: Optional[str] = None
    m = _LEAD_QTY.match(seg)
    if m:
        if m.group("num"):
            qty, rest = int(m.group("num")), seg[m.end():]
        elif m.group("half"):
            qty, rest = 6, seg[m.end():]
        elif m.group("adozen"):
            qty, rest = 12, seg[m.end():]
        else:
            w = m.group("word").lower()
            if w in _NUM_WORDS:
                qty, rest, word_used = _NUM_WORDS[w], seg[m.end():], w
            else:
                qty, rest = 1, seg  # no quantity given
    else:
        qty, rest = 1, seg
    rest = re.sub(r"^(?:of|pcs|pc|pieces|piece|nos)\b\.?\s*", "", rest.strip(), flags=re.I)
    return (qty, rest.strip(), word_used) if rest.strip() else None


def _trusted(item: str) -> bool:
    matches = find_catalog_matches(item)
    if not matches:
        return False
    tiers = {m.get("match_tier") for m in matches}
    return bool(tiers) and tiers.issubset(_TRUSTED_TIERS)


def local_parse(text: str) -> Optional[list[dict]]:
    """Lines [{spoken,item,model,qty,confidence}] or None when the LLM is needed."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or _has_arabic_script(t) or len(t) > 400:
        return None
    # Characters we don't expect in a simple order → let the LLM sanitize it
    if re.search(r"[^\w\s,;+&.\-/()'x]", t, flags=re.UNICODE):
        return None

    segments = _split_segments(t)
    if not segments or len(segments) > 12:
        return None

    lines: list[dict] = []
    for seg in segments:
        taken = _take_qty(seg)
        if not taken:
            return None
        qty, item, word_used = taken
        if qty < 1 or qty > 9999:
            return None
        # A leftover standalone number at the end ("chain kit 5") is a trailing
        # quantity (or a part number) → ambiguous, ask the LLM.
        if re.search(r"(?:^|\s)\d{1,3}$", item) and not re.search(r"[A-Za-z]\d+$", item):
            return None
        if re.search(r"\b(?:qty|quantity|pcs|pieces)\b", item, flags=re.I):
            return None

        # Another quantity inside the item text ("mujhe paanch chain kit chahiye",
        # "chain kit do basket") → the split is unclear, ask the LLM.
        for tok in item.lower().split():
            if tok in LATIN_QTY_WORDS or (tok.isdigit() and len(tok) <= 3):
                return None

        if not _trusted(item):
            return None
        # A quantity word that is ALSO a real catalog word (e.g. a part called
        # "... TWO ...") is ambiguous → let the LLM decide.
        if word_used and word_used in catalog_vocab():
            return None

        lines.append(
            {
                "spoken": item,  # quantity/filler words stripped: nothing to re-interpret
                "item": item,
                "model": None,
                "qty": qty,
                "confidence": "exact",
            }
        )
    return lines or None
