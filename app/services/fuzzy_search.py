"""RapidFuzz offline order parsing and catalog ranking."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from rapidfuzz import fuzz, process, utils as rf_utils

from app.database.queries import get_all_items_for_fuzzy, items_version, search_items_by_name

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

# Spoken/Urdu part words → English catalog tokens (not a full alias dictionary —
# only bridges script so "چین کٹ" can require CHAIN+KIT in the name).
PART_WORD_ALIASES = {
    "چین": "chain",
    "کٹ": "kit",
    "کِٹ": "kit",
    "بیرنگ": "bearing",
    "بیئرنگ": "bearing",
    "فلٹر": "filter",
    "فلتر": "filter",
    "ایئر": "air",
    "ائیر": "air",
    "بیک": "back",
    "لائٹ": "light",
    "لائیٹ": "light",
    "ہیڈ": "head",
    "ہید": "head",
    "لینز": "lens",
    "کمپلیٹ": "complete",
    "کمپلت": "complete",
    "آئل": "oil",
    "سیل": "seal",
    "کلچ": "clutch",
    "کیبل": "cable",
    "باسکٹ": "basket",
    "بسکٹ": "basket",
    "یونٹ": "unit",
}

PART_PHRASE_ALIASES = {
    "ایل ای ڈی": "led",
    "سی ڈی آئی": "cdi",
    "سی ڈی آئی یونٹ": "cdi unit",
    "ایئر فلٹر": "air filter",
    "ائیر فلٹر": "air filter",
    "چین کٹ": "chain kit",
    "چین لوگ": "chain lock",
    "بیک لائٹ": "back light",
    "ہیڈ لائٹ": "head light",
}
_PHRASES_LONGEST_FIRST = sorted(PART_PHRASE_ALIASES.items(), key=lambda kv: -len(kv[0]))

QUERY_STOPWORDS = set(URDU_QTY_WORDS.keys()) | {
    "for",
    "of",
    "the",
    "and",
    "a",
    "an",
    "with",
    "to",
    "اور",
    "کا",
    "کی",
    "کے",
    "پر",
}


# English + Roman-Urdu quantity words (used by the offline parser and the local fast path)
LATIN_QTY_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "dozen": 12,
    "ek": 1, "aik": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "panch": 5,
    "paanch": 5, "pach": 5, "chay": 6, "che": 6, "chhe": 6, "saat": 7, "sat": 7,
    "aath": 8, "ath": 8, "nau": 9, "das": 10, "dus": 10,
}

# Quantity words are never part of an item phrase ("paanch chain kit" → "chain kit")
QUERY_STOPWORDS.update(LATIN_QTY_WORDS)
# Request filler ("please give me ...", "... chahiye"). Deliberately NOT included:
# pcs / piece / set, which are real catalog words.
QUERY_STOPWORDS.update({
    "please", "pls", "kindly", "give", "me", "i", "need", "want", "add", "also",
    "send", "order", "qty", "quantity", "nos", "chahiye", "chahye", "chahiay",
    "dena", "dedo", "bhai", "mujhe", "hai", "bhejo", "karo",
})

_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})


def normalize_transcript(text: str) -> str:
    """Make raw input safe/uniform: drop markup & control chars, ASCII digits, 1 space."""
    t = text or ""
    t = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<[^>]{0,200}>", " ", t)
    t = t.translate(_DIGIT_MAP)
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", t)
    # invisible joiners/marks: removing (not spacing) keeps Urdu words intact
    t = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# Roman-Urdu words that can't be mistaken for English part words
_ROMAN_QTY = {k: v for k, v in LATIN_QTY_WORDS.items()
              if k in {"ek", "aik", "teen", "char", "chaar", "panch", "paanch", "pach",
                       "chay", "chhe", "saat", "aath", "nau", "das", "dus"}}


def leading_qty_hint(spoken: str) -> Optional[int]:
    """Unambiguous quantity at the very start of a phrase (digits / Urdu / Roman Urdu)."""
    t = normalize_transcript(spoken)
    if not t:
        return None
    first, _, tail = t.partition(" ")
    if not tail:
        return None
    if first.isdigit():
        # ≤3 digits only: "6203 bearing" starts with a part number, not a quantity
        return int(first) if (len(first) <= 3 and int(first) > 0) else None
    if first in URDU_QTY_WORDS:
        return URDU_QTY_WORDS[first]
    return _ROMAN_QTY.get(first.lower())


def qty_before_phrase(text: str, phrase: str) -> Optional[int]:
    """Urdu / Roman-Urdu quantity word right before `phrase` in `text`
    (the LLM sometimes strips it out of its own 'spoken' field)."""
    t, ph = (text or ""), (phrase or "").strip()
    if not t or not ph:
        return None
    idx = t.lower().find(ph.lower())
    if idx <= 0:
        return None
    prev = t[:idx].split()
    if not prev:
        return None
    w = prev[-1]
    if w in URDU_QTY_WORDS:
        return URDU_QTY_WORDS[w]
    return _ROMAN_QTY.get(w.lower())


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

    # "2 basket", "2x basket", "2 x basket"; never split one number ("1234") or eat
    # the first letter of a word ("2 xenon" must stay "xenon").
    m = re.match(r"^(\d+)\s*(?:[xX](?=\s|$)\s*)?(\D.*)$", text)
    if m:
        return max(1, int(m.group(1))), m.group(2).strip()

    parts = text.split(" ", 1)
    if parts and parts[0] in URDU_QTY_WORDS:
        rest = parts[1].strip() if len(parts) > 1 else ""
        return URDU_QTY_WORDS[parts[0]], rest

    return 1, text


def _qty_start_pattern() -> re.Pattern:
    # Longest Urdu qty words first so "پچاس" wins over shorter overlaps
    words = sorted(URDU_QTY_WORDS.keys(), key=len, reverse=True)
    urdu = "|".join(re.escape(w) for w in words)
    # Digit qty or Urdu qty word at a token boundary
    return re.compile(rf"(?:(?<=^)|(?<=\s))((?:\d+)|(?:{urdu}))(?=\s+\S)", re.UNICODE)


def split_on_interior_qtys(text: str) -> list[tuple[int, str]]:
    """
    Split a single spoken phrase that embeds multiple qty+item segments, e.g.
    'چھ بیک لائٹ ایل ای ڈی 10 سی ڈی آئی یونٹ' → (6, back light…), (10, cdi…).
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []

    matches = list(_qty_start_pattern().finditer(text))
    if len(matches) <= 1:
        qty, rest = strip_leading_qty(text)
        return [(qty, rest or text)] if (rest or text) else []

    parts: list[tuple[int, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[m.start() : end].strip()
        qty, rest = strip_leading_qty(chunk)
        if rest:
            parts.append((qty, rest))
        elif chunk:
            parts.append((qty, chunk))
    return parts if parts else [(1, text)]


def expand_order_lines(lines: list[dict], transcript: str) -> list[dict]:
    """
    Repair under-split LLM output when the transcript clearly has multiple qty markers.
    Example: one merged line for
    'چھ بیک لائٹ ایل ای ڈی 10 سی ڈی آئی یونٹ' → two lines (qty 6 + qty 10).
    """
    transcript = (transcript or "").strip()
    lines = list(lines or [])
    if not lines:
        # The parser (LLM or fuzzy) found no order items: that IS the noise verdict.
        # Never resurrect lines from the raw transcript.
        return []
    transcript_parts = split_on_interior_qtys(transcript) if transcript else []

    # Transcript has more qty segments than LLM lines → rebuild from transcript
    if transcript_parts and len(transcript_parts) > len(lines):
        return [
            {
                "spoken": phrase,
                "item": phrase,
                "model": None,
                "qty": qty,
                "confidence": "ambiguous",
            }
            for qty, phrase in transcript_parts
        ]

    # Expand any individual spoken field that still embeds multiple qtys
    expanded: list[dict] = []
    for line in lines:
        spoken = (line.get("spoken") or line.get("item") or "").strip()
        parts = split_on_interior_qtys(spoken)
        if len(parts) <= 1:
            expanded.append(line)
            continue
        for i, (qty, phrase) in enumerate(parts):
            if i == 0:
                expanded.append(
                    {
                        "spoken": phrase,
                        "item": line.get("item") or phrase,
                        "model": line.get("model"),
                        "qty": qty,
                        "confidence": line.get("confidence") or "ambiguous",
                    }
                )
            else:
                expanded.append(
                    {
                        "spoken": phrase,
                        "item": phrase,
                        "model": None,
                        "qty": qty,
                        "confidence": "ambiguous",
                    }
                )
    return expanded or lines


def clean_item_query(text: str) -> str:
    """Remove leading qty words so Urdu/English search hits the part name."""
    _qty, rest = strip_leading_qty(text)
    return (rest or text or "").strip()


def content_tokens(text: str) -> list[str]:
    """
    Significant search tokens in English catalog form.
    Maps common Urdu part words so coverage checks work across scripts.
    """
    t = (text or "").strip().lower()
    if not t:
        return []
    for phrase, eng in _PHRASES_LONGEST_FIRST:
        if phrase in t:
            t = t.replace(phrase, " " + eng + " ")
    raw = [x for x in re.split(r"[^\w\u0600-\u06FF]+", t) if x]
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw:
        if tok in QUERY_STOPWORDS or len(tok) < 2:
            continue
        if tok.isdigit():
            continue
        mapped = PART_WORD_ALIASES.get(tok, tok)
        # Drop leftover Arabic tokens that didn't map
        if re.search(r"[\u0600-\u06FF]", mapped):
            continue
        if mapped in QUERY_STOPWORDS or mapped in seen:
            continue
        seen.add(mapped)
        out.append(mapped)
    return out


def english_query_hint(text: str) -> str:
    """Best-effort English phrase for SQL LIKE when input is Urdu."""
    return " ".join(content_tokens(text)).strip()


def filter_matches_by_content_tokens(matches: list[dict], query: str) -> list[dict]:
    """
    Keep catalog rows that actually contain the query's content words.
    Prefer contiguous phrase matches (e.g. 'chain kit') so CHAIN COVER / CHAIN LOCK
    don't crowd out CHAIN KIT.
    """
    if not matches:
        return []
    tokens = content_tokens(query)
    if len(tokens) < 2:
        # Single meaningful token: still prefer names containing it
        if len(tokens) == 1:
            tok = tokens[0]
            hit = [
                m
                for m in matches
                if tok in f"{m.get('name') or ''} {m.get('urdu_name') or ''}".lower()
            ]
            return hit or matches
        return matches

    phrase = " ".join(tokens)

    def blob(m: dict) -> str:
        return f"{m.get('name') or ''} {m.get('urdu_name') or ''}".lower()

    phrase_hits = [m for m in matches if phrase in blob(m)]
    if phrase_hits:
        # Keep ALL phrase hits (e.g. TIMING CHAIN KIT), but rank
        # names that start with the phrase first (CHAIN KIT …).
        def rank_key(m: dict) -> tuple:
            name = (m.get("name") or "").lower()
            headed = 0 if name.startswith(phrase) else 1
            score = -float(m.get("score") or 0)
            return (headed, score, name)

        return sorted(phrase_hits, key=rank_key)

    full = [m for m in matches if all(tok in blob(m) for tok in tokens)]
    if full:
        return full

    # Soft: require majority of tokens
    need = max(2, (len(tokens) + 1) // 2)
    soft = [
        m
        for m in matches
        if sum(1 for tok in tokens if tok in blob(m)) >= need
    ]
    if soft:
        return soft

    # Last resort: keep rows containing the first content token (not the whole fuzzy pile)
    primary = tokens[0]
    primary_hits = [m for m in matches if primary in blob(m)]
    return primary_hits or matches


def filter_to_best_name_families(matches: list[dict], query: str) -> list[dict]:
    """After token filter, drop weak name families far below the best score."""
    matches = filter_matches_by_content_tokens(matches, query)
    if len(matches) <= 1:
        return matches
    scored = sorted(matches, key=lambda m: float(m.get("score") or 0), reverse=True)
    best = float(scored[0].get("score") or 0)
    if not best:
        return matches
    return [m for m in scored if float(m.get("score") or 0) >= best - 12] or matches


# Canonical English part-type discriminators (catalog-facing).
# Aliases (Urdu / synonyms) map into these — never treat as bike models.
DISC_ALIAS_TO_CANON: dict[str, str] = {
    "complete": "complete",
    "کمپلیٹ": "complete",
    "کمپلت": "complete",
    "led": "led",
    "ایل_ای_ڈی": "led",
    "lens": "lens",
    "لینز": "lens",
    "assy": "assy",
    "assembly": "assy",
    "set": "set",
    "kit": "kit",
    "cover": "cover",
    "rubber": "rubber",
    "bush": "bush",
    "bearing": "bearing",
    "seal": "seal",
    "gasket": "gasket",
}

# Substrings that count as a hit for each canonical discriminator in name/urdu.
DISC_NAME_FORMS: dict[str, tuple[str, ...]] = {
    "complete": ("complete", "کمپلیٹ", "کمپلت"),
    "led": ("led", "ایل ای ڈی"),
    "lens": ("lens", "لینز"),
    "assy": ("assy", "assembly"),
    "set": ("set",),
    "kit": ("kit",),
    "cover": ("cover",),
    "rubber": ("rubber",),
    "bush": ("bush",),
    "bearing": ("bearing",),
    "seal": ("seal",),
    "gasket": ("gasket",),
}

PART_TYPE_TOKENS = set(DISC_ALIAS_TO_CANON.keys())

# Multi-word phrases normalized before tokenization (language-general, not item-specific)
PART_TYPE_PHRASES = (
    "ایل ای ڈی",
)


def sanitize_model_hint(model: Optional[str]) -> Optional[str]:
    """Drop hints that are part-type words (LED, COMPLETE, …), not bike models."""
    if not model:
        return None
    m = str(model).strip()
    if not m:
        return None
    low = m.lower().replace("-", " ").strip()
    if low in DISC_ALIAS_TO_CANON or low.replace(" ", "_") in DISC_ALIAS_TO_CANON:
        return None
    return m


def fold_part_type_into_query(item_query: str, model: Optional[str]) -> tuple[str, Optional[str]]:
    """
    If LLM put COMPLETE/LED/LENS in model, move it into the item query
    and clear the model hint.
    """
    q = (item_query or "").strip()
    safe = sanitize_model_hint(model)
    if safe is not None:
        return q, safe
    raw = (model or "").strip()
    if not raw:
        return q, None
    # Fold discarded model token into query if not already present
    if raw.lower() not in q.lower():
        q = f"{q} {raw}".strip()
    return q, None


def _query_tokens(text: str) -> list[str]:
    t = (text or "").lower()
    for phrase in PART_TYPE_PHRASES:
        t = t.replace(phrase, phrase.replace(" ", "_"))
    return [x for x in re.split(r"[^\w\u0600-\u06FF]+", t) if len(x) >= 2]


def canonical_discriminators(text: str) -> set[str]:
    """Return canonical part-type discriminators found in text (English keys)."""
    found: set[str] = set()
    low = (text or "").lower()
    for phrase in PART_TYPE_PHRASES:
        if phrase in low:
            key = phrase.replace(" ", "_")
            canon = DISC_ALIAS_TO_CANON.get(key) or DISC_ALIAS_TO_CANON.get(phrase)
            if canon:
                found.add(canon)
    for tok in _query_tokens(text):
        canon = DISC_ALIAS_TO_CANON.get(tok) or DISC_ALIAS_TO_CANON.get(
            tok.replace("_", " ")
        )
        if canon:
            found.add(canon)
    return found


def _discriminator_tokens(text: str) -> set[str]:
    """Alias for canonical_discriminators (canonical English keys)."""
    return canonical_discriminators(text)


def name_has_discriminator(name: str, urdu: str, canon: str) -> bool:
    blob = f"{name or ''} {urdu or ''}".lower()
    for form in DISC_NAME_FORMS.get(canon, (canon,)):
        if form in blob:
            return True
    return False


def name_matches_discriminators(name: str, urdu: str, discs: set[str]) -> bool:
    if not discs:
        return True
    return all(name_has_discriminator(name, urdu, d) for d in discs)


def strip_part_type_from_text(text: str) -> str:
    """Remove known part-type words/phrases so a stem can be rebuilt."""
    t = (text or "").strip()
    if not t:
        return ""
    low = t.lower()
    for phrase in sorted(PART_TYPE_PHRASES, key=len, reverse=True):
        if phrase in low:
            # case-sensitive replace on original via regex ignore case for Latin only
            t = re.sub(re.escape(phrase), " ", t, flags=re.IGNORECASE)
            low = t.lower()
    # Token-wise strip of aliases
    parts = re.split(r"(\s+)", t)
    kept = []
    for p in parts:
        if not p or p.isspace():
            kept.append(p)
            continue
        key = p.lower().strip()
        if key in DISC_ALIAS_TO_CANON:
            continue
        kept.append(p)
    return re.sub(r"\s+", " ", "".join(kept)).strip(" -,/")


def _ensure_canonical_in_query(base: str, discs: set[str]) -> str:
    """Append missing canonical English discs so SQL LIKE hits English catalog names."""
    out = (base or "").strip()
    low = out.lower()
    for d in sorted(discs):
        if any(form in low for form in DISC_NAME_FORMS.get(d, (d,))):
            continue
        token = d.upper() if d.isascii() else d
        out = f"{out} {token}".strip()
        low = out.lower()
    return out


def reconcile_item_with_spoken(item: str, spoken: str) -> str:
    """
    Prefer part-type words from the original spoken/typed phrase when the LLM
    item omits them or picks a conflicting sibling (e.g. spoken COMPLETE → item LED).

    Also prefer spoken Urdu→English content (چین کٹ → chain kit) when the LLM
    invents a wrong English label (CHAIN CUT).
    """
    item = (item or "").strip()
    spoken = (spoken or "").strip()
    spoken_d = canonical_discriminators(spoken)
    item_d = canonical_discriminators(item)
    spoken_tokens = content_tokens(spoken)
    item_tokens = content_tokens(item)
    spoken_hint = english_query_hint(spoken)

    # Spoken maps to a clear English phrase that diverges from LLM item
    if spoken_hint and spoken_tokens:
        if not item_tokens or set(spoken_tokens) != set(item_tokens):
            # e.g. spoken chain+kit vs LLM chain+cut
            if not set(spoken_tokens).issubset(set(item_tokens)):
                return spoken_hint

    if item and not _has_arabic_script(item):
        base = item
    elif spoken and not _has_arabic_script(spoken):
        base = spoken
    else:
        base = item or spoken or spoken_hint

    if not spoken_d:
        return base

    # Spoken discs already present on item — keep English base, ensure catalog words
    if spoken_d.issubset(item_d):
        return _ensure_canonical_in_query(base, spoken_d)

    # Missing or conflicting: strip item's part-type tokens, apply spoken's
    stem = strip_part_type_from_text(base)
    if not stem:
        stem = strip_part_type_from_text(spoken) or base
    # If stem is still Arabic-only, keep LLM English stem when available
    if _has_arabic_script(stem) and item and not _has_arabic_script(item):
        stem = strip_part_type_from_text(item) or stem
    return _ensure_canonical_in_query(stem, spoken_d)


def rerank_by_query_tokens(matches: list[dict], query: str) -> list[dict]:
    """
    Boost rows whose name contains query content tokens / discriminators.
    Prefer contiguous phrases (chain kit) over loose CHAIN* + *KIT* hits.
    """
    if not matches:
        return []
    # Exact-first cascade rows are already tiered + ranked; never re-mix them.
    if all(m.get("match_tier") in EXACT_TIERS for m in matches):
        return list(matches)
    disc = canonical_discriminators(query)
    content = content_tokens(query)
    phrase = " ".join(content) if len(content) >= 2 else ""

    def boost(m: dict) -> float:
        name = m.get("name") or ""
        urdu = m.get("urdu_name") or ""
        blob = f"{name} {urdu}".lower()
        score = float(m.get("score") or 0)
        if disc:
            hits = sum(1 for d in disc if name_has_discriminator(name, urdu, d))
            if hits == len(disc):
                score += 25
            elif hits:
                score += 8 * hits
            else:
                score -= 15
        if phrase and phrase in blob:
            score += 30
        elif content:
            tok_hits = sum(1 for t in content if t in blob)
            score += tok_hits * 6
            if tok_hits < len(content):
                score -= 10 * (len(content) - tok_hits)
        return score

    scored = []
    for m in matches:
        row = dict(m)
        row["score"] = boost(m)
        scored.append(row)
    scored.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    return filter_to_best_name_families(scored, query)


# ---------------------------------------------------------------------------
# Exact-first cascade
#   code → exact name → contiguous phrase → all words → (n-1 words) → fuzzy
# Each stage only runs if the previous one found nothing, so a precise request
# never gets diluted by loosely related rows.
# ---------------------------------------------------------------------------

TIER_CODE = "code"
TIER_EXACT = "exact"
TIER_PHRASE = "phrase"
TIER_WORDS = "words"
TIER_MOST = "most_words"
EXACT_TIERS = {TIER_CODE, TIER_EXACT, TIER_PHRASE, TIER_WORDS, TIER_MOST}

_TIER_BASE_SCORE = {
    TIER_CODE: 100.0,
    TIER_EXACT: 98.0,
    TIER_PHRASE: 90.0,
    TIER_WORDS: 84.0,
    TIER_MOST: 72.0,
}


def _norm_text(text: str) -> str:
    """Lowercase, drop dots (C.D.I. → cdi), punctuation → spaces."""
    t = (text or "").lower().replace(".", "")
    t = re.sub(r"[^\w\u0600-\u06FF]+", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def _stem(tok: str) -> str:
    # Plural → singular for plain words (bearings → bearing). Applied to both sides.
    if tok.isalpha() and len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


@lru_cache(maxsize=100_000)
def _name_tokens_t(text: str) -> tuple:
    return tuple(_stem(t) for t in _norm_text(text).split() if t)


def _name_tokens(text: str) -> list[str]:
    return list(_name_tokens_t(text))


@lru_cache(maxsize=100_000)
def _norm_text_cached(text: str) -> str:
    return _norm_text(text)


_DERIVED: dict = {"version": -1}


def _derived() -> dict:
    """Per-catalog-version derived data (model sequences, vocab, fuzzy labels).

    Built into a fresh dict and swapped in one assignment so request threads
    never observe a half-built index.
    """
    global _DERIVED
    ver = items_version()
    if _DERIVED.get("version") != ver:
        items = get_all_items_for_fuzzy()
        model_seqs = {
            _name_tokens_t(m.get("model") or "")
            for m in items
            if m.get("model")
        }
        model_seqs.discard(())
        vocab: set[str] = set()
        for i in items:
            vocab.update(_name_tokens_t(i.get("name") or ""))
            vocab.update(_name_tokens_t(i.get("model") or ""))
        vocab.discard("")
        _DERIVED = {
            "version": ver,
            "model_seqs": model_seqs,
            "vocab": vocab,
            "vocab_list": list(vocab),
            "choices": None,
        }
    return _DERIVED


def analyze_query(text: str) -> tuple[list[str], int]:
    """
    Query → (search tokens incl. digits & stemmed, count of Urdu words we could
    not map to English). Unmapped words mean the English view of the query is
    incomplete, so exact tiers must not be trusted.
    """
    t = (text or "").lower().replace(".", "")
    for phrase, eng in _PHRASES_LONGEST_FIRST:
        if phrase in t:
            t = t.replace(phrase, " " + eng + " ")
    raw = [x for x in re.split(r"[^\w\u0600-\u06FF]+", t) if x]
    out: list[str] = []
    unmapped = 0
    for tok in raw:
        if tok in QUERY_STOPWORDS:
            continue
        mapped = PART_WORD_ALIASES.get(tok, tok)
        if re.search(r"[\u0600-\u06FF]", mapped):
            unmapped += 1
            continue
        if mapped in QUERY_STOPWORDS:
            continue
        for piece in mapped.split():
            piece = _stem(piece)
            if piece and piece not in out:
                out.append(piece)
    return out, unmapped


def _contains_seq(hay: list[str], needle: list[str]) -> int:
    """Index of first contiguous occurrence of needle in hay, or -1."""
    n = len(needle)
    if n == 0 or n > len(hay):
        return -1
    hay = tuple(hay)
    needle = tuple(needle)
    for i in range(len(hay) - n + 1):
        if hay[i : i + n] == needle:
            return i
    return -1


def _extract_model_hint(items: list[dict], tokens: list[str]) -> tuple[list[str], list[str]]:
    """
    Pull a bike model out of the query tokens when the LLM left it in the item
    text (e.g. 'air filter cd70'). Returns (remaining_tokens, model_tokens).
    """
    model_seqs = _derived()["model_seqs"]
    best: tuple = ()
    for seq in model_seqs:
        if not seq:
            continue
        if _contains_seq(tokens, list(seq)) >= 0 and len(seq) > len(best):
            best = seq
    if not best:
        # Partial model word, e.g. 'cd70' (catalog has CD70-CDI, CD70F, CD70 EURO-2):
        # accept a single digit-bearing token that appears inside some model.
        vocab = {t for seq in model_seqs for t in seq if any(c.isdigit() for c in t)}
        for tok in tokens:
            if tok in vocab and any(c.isalpha() for c in tok):
                best = (tok,)
                break
    if not best:
        return tokens, []
    idx = _contains_seq(tokens, list(best))
    remaining = tokens[:idx] + tokens[idx + len(best) :]
    if not remaining:  # query was ONLY a model name → not a part search
        return tokens, []
    return remaining, list(best)


def _model_matches(row_model: str, hint: list[str]) -> bool:
    if not hint:
        return True
    return _contains_seq(_name_tokens(row_model), hint) >= 0


def _cascade_rank(rows: list[dict], tokens: list[str], tier: str) -> list[dict]:
    """Annotate + order rows: names that START with the phrase, then shorter names."""
    base = _TIER_BASE_SCORE[tier]
    scored = []
    for r in rows:
        nt = _name_tokens(r.get("name") or "")
        pos = _contains_seq(nt, tokens)
        extra = max(0, len(nt) - len(tokens))
        head_bonus = 2.0 if pos == 0 else 0.0
        score = base + head_bonus - min(extra * 0.4, 8.0)
        row = dict(r)
        row["score"] = round(score, 2)
        row["match_tier"] = tier
        scored.append(row)
    scored.sort(
        key=lambda x: (-float(x["score"]), (x.get("name") or "").lower(), x.get("model") or "")
    )
    return scored


def exact_first_matches(
    items: list[dict],
    query: str,
    model: Optional[str] = None,
) -> list[dict]:
    """
    Exact-first lookup. Returns [] when nothing is found at any exact tier
    (caller then falls back to fuzzy).
    """
    q = (query or "").strip()
    if not q or not items:
        return []

    # 0) Item code typed/spoken exactly
    qn = _norm_text(q)
    code_hits = [i for i in items if qn and _norm_text_cached(i.get("item_code") or "") == qn]
    if code_hits:
        return _cascade_rank(code_hits, [qn], TIER_CODE)

    # 1) Urdu catalog name matches the Urdu query verbatim
    if _has_arabic_script(q):
        ur_hits = [i for i in items if (i.get("urdu_name") or "").strip() == q.strip()]
        if ur_hits:
            return _cascade_rank(ur_hits, _name_tokens(ur_hits[0].get("name") or ""), TIER_EXACT)

    tokens, unmapped = analyze_query(q)
    if unmapped or not tokens:
        return []  # incomplete English view → let fuzzy handle it

    tokens, model_from_text = _extract_model_hint(items, tokens)
    model_hint = _name_tokens(model or "") or model_from_text

    def run(pool: list[dict]) -> list[dict]:
        # 2) Full catalog name equals the request
        want = tuple(tokens)
        named = [(i, _name_tokens_t(i.get("name") or "")) for i in pool]
        exact = [i for i, nt in named if nt == want]
        if exact:
            return _cascade_rank(exact, tokens, TIER_EXACT)

        # 3) Request is a contiguous phrase inside the name (chain kit → … CHAIN KIT …)
        phrase = [i for i, nt in named if _contains_seq(nt, tokens) >= 0]
        if phrase:
            return _cascade_rank(phrase, tokens, TIER_PHRASE)

        # 4) Every word present, any order, whole words only
        tset = set(tokens)
        words = [i for i, nt in named if tset.issubset(nt)]
        if words:
            return _cascade_rank(words, tokens, TIER_WORDS)

        # 5) All but one word (only for 3+ word requests; guards stray LLM words)
        if len(tokens) >= 3:
            need = len(tokens) - 1
            most = [
                i
                for i, nt in named
                if sum(1 for t in tset if t in nt) >= need
            ]
            if most:
                return _cascade_rank(most, tokens, TIER_MOST)
        return []

    if model_hint:
        with_model = [i for i in items if _model_matches(i.get("model") or "", model_hint)]
        hits = run(with_model)
        if hits:
            return hits
        # Part exists but not for that bike → show the part for all models (soft hint)
    return run(items)


_FILLER_WORDS = {
    "hello", "hi", "hey", "how", "are", "you", "the", "and", "for", "ok", "okay",
    "thanks", "thank", "bye", "yes", "no", "please", "give", "need", "want", "can",
    "will", "this", "that", "with", "from", "have", "got", "now", "then", "noise",
    "background", "hmm", "umm", "yeah",
}


def catalog_vocab(items: Optional[list[dict]] = None) -> set[str]:
    if items is None:
        return _derived()["vocab"]
    vocab: set[str] = set()
    for i in items:
        vocab.update(_name_tokens_t(i.get("name") or ""))
        vocab.update(_name_tokens_t(i.get("model") or ""))
    return {v for v in vocab if v}


def transcript_matches_catalog(text: str) -> bool:
    """
    Cheap relevance gate. False → the transcript shares no word with the catalog
    (chatter / background noise), so we skip the LLM instead of letting it
    hallucinate a part. Digits and Urdu script always pass (handled elsewhere).
    """
    t = (text or "").strip()
    if not t:
        return False
    if _has_arabic_script(t):
        return True
    d = _derived()
    vocab, vocab_list = d["vocab"], d["vocab_list"]
    if re.search(r"\d", t):
        # Digits next to words (Roman-Urdu orders etc.) are judged by the LLM later.
        # Bare numbers ("1234") only count when they are a real part number/code.
        if re.search(r"[A-Za-z]{2,}", t):
            return True
        nums = re.findall(r"\d+", t)
        codes = {_norm_text_cached(i.get("item_code") or "") for i in get_all_items_for_fuzzy()}
        return any(n in vocab or n in codes for n in nums)
    for tok in _name_tokens(t):
        if len(tok) < 3 or tok in _FILLER_WORDS or tok in QUERY_STOPWORDS:
            continue
        if tok in vocab:
            return True
        if len(tok) >= 4 and process.extractOne(
            tok, vocab_list, scorer=fuzz.ratio, score_cutoff=85
        ):
            return True
    return False


def find_catalog_matches(
    item_query: str,
    model: Optional[str] = None,
    limit: int = 150,
) -> list[dict]:
    """
    Resolve spoken/typed item text to catalog rows, exact-first:
    code → exact name → phrase → all words → fuzzy fallback.
    """
    q, model = fold_part_type_into_query(item_query, model)
    q = clean_item_query(q)
    if not q:
        return []
    model = sanitize_model_hint(model)

    items = get_all_items_for_fuzzy()
    hits = exact_first_matches(items, q, model)
    if hits:
        return hits[:limit]
    return _fuzzy_fallback_matches(q, model, limit)


def _fuzzy_fallback_matches(
    q: str,
    model: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Last resort when no exact tier hits: SQL LIKE + RapidFuzz (typos, Urdu
    spelling variants e.g. sheet ائیر لوٹا vs spoken ایئر لوٹا).
    """
    eng_hint = english_query_hint(q)

    like_matches = search_items_by_name(q, model, limit=limit)
    if not like_matches and model:
        like_matches = search_items_by_name(q, None, limit=limit)

    # Urdu spoken → try English catalog phrase (چین کٹ → chain kit)
    if not like_matches and eng_hint and eng_hint.lower() != q.lower():
        like_matches = search_items_by_name(eng_hint, model, limit=limit)
        if not like_matches and model:
            like_matches = search_items_by_name(eng_hint, None, limit=limit)

    if not like_matches:
        like_matches = search_items_by_name(q, None, limit=limit)

    disc = canonical_discriminators(q)
    rank_q = eng_hint or q
    # Early LIKE return only when hits already match content tokens
    if like_matches and not _has_arabic_script(q):
        ranked = rerank_by_query_tokens(
            [{**m, "score": m.get("score") or 90} for m in like_matches], rank_q
        )
        if disc or len(content_tokens(rank_q)) >= 2:
            return ranked[:limit]
        return like_matches[:limit]

    fuzzy_q = eng_hint if (_has_arabic_script(q) and eng_hint) else q
    fuzzy = rank_catalog(fuzzy_q, limit=max(limit, 40), preferred_model=model)
    if not fuzzy and model:
        fuzzy = rank_catalog(fuzzy_q, limit=max(limit, 40))
    # Also fuzzy original Urdu if English hint path was weak
    if fuzzy_q != q:
        fuzzy_ur = rank_catalog(q, limit=max(limit, 40), preferred_model=model)
        if fuzzy_ur:
            seen_f = {r["id"] for r in fuzzy}
            for row in fuzzy_ur:
                if row["id"] not in seen_f:
                    fuzzy.append(row)

    if fuzzy:
        best = float(fuzzy[0].get("score") or 0)
        min_score = 70 if _has_arabic_script(q) and not eng_hint else 55
        fuzzy = [
            r
            for r in fuzzy
            if float(r.get("score") or 0) >= max(min_score, best - 12)
        ]

    if not like_matches:
        return rerank_by_query_tokens(fuzzy, rank_q)[:limit]

    seen = {m["id"] for m in like_matches}
    merged = [{**m, "score": m.get("score") or 88} for m in like_matches]
    for row in fuzzy:
        if row["id"] not in seen:
            merged.append(row)
            seen.add(row["id"])
    return rerank_by_query_tokens(merged, rank_q)[:limit]


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
    d = _derived()
    if d.get("choices") is None:
        d["choices"] = _build_choices(items)
    labels, mapped = d["choices"]
    # processor: case/punctuation-insensitive (queries are often lowercase; catalog is UPPER)
    hits = process.extract(
        q, labels, scorer=fuzz.WRatio, processor=rf_utils.default_process, limit=limit * 3
    )
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
        if qty == 1 and rest == chunk:
            first, _, tail = chunk.partition(" ")
            if tail and first.lower() in LATIN_QTY_WORDS:
                qty, rest = LATIN_QTY_WORDS[first.lower()], tail.strip()
        # Chunk that is only quantity words / digits ("ایک دو تین") is not an item
        words = [w for w in re.split(r"\s+", rest or chunk) if w]
        if all(w in URDU_QTY_WORDS or w.isdigit() or w.lower() in LATIN_QTY_WORDS for w in words):
            continue
        results.append((qty, rest or chunk))
    return results


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

        # Urdu script: bridge to English catalog words we know (باسکٹ → basket)
        hint = ""
        if _has_arabic_script(clean):
            toks, unmapped = analyze_query(clean)
            # a partly-mapped phrase ("ائیر لوٹا" → only "air") would mislead: no hint then
            hint = " ".join(toks) if (toks and not unmapped) else ""
        query_text = hint or clean or phrase

        hits = process.extract(
            query_text,
            labels,
            scorer=fuzz.WRatio,
            processor=rf_utils.default_process,
            limit=5,
        )
        best_label, best_score, best_idx = hits[0]
        if _has_arabic_script(phrase) and not hint:
            # Unknown Urdu words: only trust a close whole-string match (WRatio's partial
            # matching happily "finds" short labels inside any long sentence).
            sim = fuzz.ratio(
                rf_utils.default_process(query_text), rf_utils.default_process(best_label)
            )
            if best_score < 82 or sim < 75:
                continue
        best_item = mapped[best_idx]
        # Prefer English catalog name for downstream search/display
        item_name = hint or best_item.get("name") or clean or phrase

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
