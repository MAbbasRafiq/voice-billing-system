"""AI order parser: Groq → Gemini → RapidFuzz."""

from __future__ import annotations

import json
import os
import re
import time
from collections import OrderedDict
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
Billing assistant for a Pakistani motorcycle spare-parts shop. Input is an order in
English, Urdu script or Roman Urdu. Return ONLY a JSON array, one object per part line:
[{"spoken":"original phrase","item":"ENGLISH CATALOG-STYLE NAME","model":"BIKE MODEL or null","qty":number,"confidence":"exact|ambiguous"}]

Rules:
- Part-type words stay IN the item, never in model: COMPLETE, LED, LENS, ASSY, SET, KIT,
  COVER, RUBBER, BUSH. "back light complete"/بیک لائٹ کمپلیٹ -> "BACK LIGHT COMPLETE";
  "back light LED"/ایل ای ڈی -> "BACK LIGHT LED".
- model = bike model only if clearly spoken (CD70, CG125...), else null. Never invent one.
- confidence "exact" only if item (and model, if any) are clear.
- Qty: ایک=1 دو=2 تین=3 چار=4 پانچ=5 چھ=6 سات=7 آٹھ=8 نو=9 دس=10; Roman Urdu
  ek=1 do=2 teen=3 char=4 paanch=5 chay=6 saat=7 aath=8 nau=9 das/dus=10;
  dozen/درجن=12, half dozen=6, pair=2. No number means 1.
- Split multi-item orders even when quantities appear mid-sentence: "پانچ X چھ Y" -> 2 lines;
  never merge a second qty+part into the previous line.
- Map Urdu part words to English names (چین کٹ -> CHAIN KIT, ایئر فلٹر -> AIR FILTER).
- Plain single parts (basket, kick, clutch, bearing, mirror, horn, tyre) are valid items.
- Ignore stray markup/symbols. If the input is noise, chatter or not a parts order return [].
"""

FORCE_ADDENDUM = """

IMPORTANT: a pre-check already confirmed this input is a spare-parts order (it may be
very short, e.g. just "2 basket" or one Urdu word with a number). Do NOT return [].
Extract every part and its quantity; if no number is given, qty is 1.
"""

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def _strip_json(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Prefer array, else object
    start_arr = text.find("[")
    end_arr = text.rfind("]")
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        if start_obj == -1 or start_arr <= start_obj:
            text = text[start_arr : end_arr + 1]
        elif start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            text = text[start_obj : end_obj + 1]
    elif start_obj != -1 and end_obj != -1 and end_obj > start_obj:
        text = text[start_obj : end_obj + 1]
    return json.loads(text)


def _normalize_results(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("Expected JSON array")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        qty = item.get("qty", 1)
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = 1
        if qty < 1:
            qty = 1
        model = item.get("model")
        if model in ("", "null", "None", None):
            model = None
        confidence = item.get("confidence") or "ambiguous"
        if confidence not in ("exact", "ambiguous"):
            confidence = "ambiguous"
        out.append(
            {
                "spoken": item.get("spoken") or item.get("item") or "",
                "item": item.get("item") or item.get("spoken") or "",
                "model": model,
                "qty": qty,
                "confidence": confidence,
            }
        )
    return out


# Groq latency is usually ~0.5s but has random multi-second stalls; a short timeout
# plus one retry recovers from a stall much faster than waiting it out.
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "3"))
# Groq models share nothing: when the main model's quota (free tier: tokens/day) is
# spent, the next one still works. Comma-separated, tried in order.
GROQ_FALLBACK_MODELS = [
    m.strip()
    for m in os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-120b").split(",")
    if m.strip()
]

_groq_client = None
_groq_key = None
_gemini_models: dict = {}
_cooldown_until: dict[str, float] = {}  # provider/model -> time.monotonic() deadline


def _in_cooldown(name: str) -> bool:
    return _cooldown_until.get(name, 0.0) > time.monotonic()


def _start_cooldown(name: str, seconds: float) -> None:
    _cooldown_until[name] = time.monotonic() + max(5.0, min(seconds, 900.0))


def _retry_after_s(exc: Exception) -> float:
    """Seconds the provider asked us to wait (Retry-After header), default 60."""
    try:
        return float(exc.response.headers.get("retry-after", 60))  # type: ignore[attr-defined]
    except Exception:
        return 60.0


def llm_status() -> dict:
    """Which providers are currently usable (for the UI / diagnostics)."""
    now = time.monotonic()
    return {
        name: round(until - now)
        for name, until in _cooldown_until.items()
        if until > now
    }


def _get_groq():
    """One shared client (keeps the HTTPS connection warm) with a hard timeout.

    SDK retries are off: we retry timeouts ourselves and never sleep on a 429.
    """
    global _groq_client, _groq_key
    key = os.getenv("GROQ_API_KEY")
    if _groq_client is None or _groq_key != key:
        from groq import Groq

        _groq_client = Groq(api_key=key, timeout=LLM_TIMEOUT_S, max_retries=0)
        _groq_key = key
    return _groq_client


def _get_gemini():
    key = os.getenv("GEMINI_API_KEY")
    if _gemini_models.get("key") != key:
        import google.generativeai as genai

        genai.configure(api_key=key)
        _gemini_models["key"] = key
        _gemini_models["model"] = genai.GenerativeModel(GEMINI_MODEL)
    return _gemini_models["model"]


def _groq_call(model: str, messages: list, temperature: float, max_tokens: int) -> str:
    import groq

    kwargs: dict = {}
    if "gpt-oss" in model:  # these models "think" by default (slow, token-hungry)
        kwargs["reasoning_effort"] = os.getenv("GROQ_REASONING_EFFORT", "low")
    client = _get_groq()
    # Long orders produce long JSON answers: give them proportionally more time.
    user_len = sum(len(m["content"]) for m in messages if m["role"] == "user")
    timeout = min(20.0, LLM_TIMEOUT_S + user_len / 60.0)
    last: Optional[Exception] = None
    for attempt in range(2):  # one retry, only for timeouts / connection / 5xx
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                **kwargs,
            )
            return response.choices[0].message.content
        except (groq.APITimeoutError, groq.APIConnectionError, groq.InternalServerError) as exc:
            last = exc
        except groq.BadRequestError as exc:
            if kwargs and "reasoning" in str(exc).lower():
                kwargs = {}  # model doesn't support the knob → retry without it
                last = exc
                continue
            raise
    assert last is not None
    raise last


def _groq_chat(system: str, user: str, temperature: float, max_tokens: int) -> str:
    """Try the main Groq model, then fallbacks. Skips models that are rate-limited."""
    import groq

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    last: Optional[Exception] = None
    for model in [GROQ_MODEL, *GROQ_FALLBACK_MODELS]:
        key = f"groq:{model}"
        if _in_cooldown(key):
            continue
        try:
            return _groq_call(model, messages, temperature, max_tokens)
        except groq.RateLimitError as exc:
            _start_cooldown(key, _retry_after_s(exc))
            last = exc
        except Exception as exc:
            last = exc
    raise last or RuntimeError("Groq unavailable (all models cooling down)")


def parse_with_groq(text: str, force: bool = False) -> list[dict]:
    system = SYSTEM_PROMPT + (FORCE_ADDENDUM if force else "")
    content = _groq_chat(system, text, temperature=0.1, max_tokens=2000)
    return _normalize_results(_strip_json(content))


def parse_with_gemini(text: str, force: bool = False) -> list[dict]:
    model = _get_gemini()
    system = SYSTEM_PROMPT + (FORCE_ADDENDUM if force else "")
    result = model.generate_content(
        system + "\n\nOrder: " + text,
        request_options={"timeout": LLM_TIMEOUT_S},
    )
    return _normalize_results(_strip_json(result.text))


def parse_with_fuzzy(text: str) -> list[dict]:
    from app.services.fuzzy_search import fuzzy_parse_order

    return fuzzy_parse_order(text)


def active_ai_mode() -> str:
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "fuzzy"


PICK_NAME_PROMPT = """
You match a spoken/typed spare-parts phrase to ONE catalog item name.

Rules:
- Choose exactly one name from CANDIDATES, copying it character-for-character.
- Honor part-type words in the phrase: COMPLETE, LED, LENS, ASSY, SET, KIT, COVER,
  and Urdu forms like کمپلیٹ (=COMPLETE), ایل ای ڈی (=LED), لینز (=LENS).
- Do NOT invent names. Do NOT pick a sibling that contradicts those words
  (e.g. never pick …LED when the phrase says COMPLETE/کمپلیٹ).
- Bike model/brand is irrelevant here — names only.
- If none fit, return null.

Return ONLY JSON (no markdown): {"name": "<exact candidate>" } or {"name": null}
"""

PICK_NAMES_BATCH_PROMPT = """
You match each order line to ONE catalog item name from that line's candidates.

Rules:
- For every line, choose exactly one name from THAT line's CANDIDATES (copy exactly),
  or null if none fit.
- Honor part-type words: COMPLETE, LED, LENS, ASSY, SET, KIT, COVER,
  and Urdu کمپلیٹ(=COMPLETE), ایل ای ڈی(=LED), لینز(=LENS).
- Do NOT invent names. Do NOT pick a sibling that contradicts those words.
- Bike model/brand is irrelevant — names only.
- Return one result per line id.

Return ONLY JSON array (no markdown):
[{ "id": 0, "name": "<exact candidate or null>" }, ...]
"""


def _match_candidate_name(chosen: str, candidates: list[str]) -> Optional[str]:
    """Map model output back to an exact candidate string."""
    if not chosen:
        return None
    c = chosen.strip()
    if c.lower() in ("null", "none", ""):
        return None
    by_lower = {x.lower(): x for x in candidates}
    if c.lower() in by_lower:
        return by_lower[c.lower()]
    # Soft contain: candidate contained in chosen or vice versa
    for name in candidates:
        if name.lower() in c.lower() or c.lower() in name.lower():
            return name
    return None


def _dedupe_names(candidates: list[str], limit: int = 25) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for n in candidates:
        n = (n or "").strip()
        if not n:
            continue
        key = n.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(n)
        if len(names) >= limit:
            break
    return names


def _llm_json(system: str, user_content: str, max_tokens: int = 200) -> Any:
    """Groq then Gemini; returns parsed JSON or None."""
    raw = None
    if os.getenv("GROQ_API_KEY"):
        try:
            raw = _strip_json(
                _groq_chat(system, user_content, temperature=0, max_tokens=max_tokens)
            )
        except Exception:
            raw = None
    if raw is None and os.getenv("GEMINI_API_KEY"):
        try:
            result = _get_gemini().generate_content(
                system + "\n\n" + user_content,
                request_options={"timeout": LLM_TIMEOUT_S},
            )
            raw = _strip_json(result.text)
        except Exception:
            raw = None
    return raw


def pick_catalog_name(
    spoken: str,
    item_hint: str,
    candidates: list[str],
) -> Optional[str]:
    """
    Ask Groq/Gemini to pick one catalog name from a shortlist.
    Returns the exact candidate string, or None if skip/fail/no fit.
    """
    names = _dedupe_names(candidates)
    if not names:
        return None
    if len(names) == 1:
        return names[0]

    user_content = (
        f"Spoken/typed: {spoken or item_hint}\n"
        f"Item hint: {item_hint or spoken}\n"
        f"CANDIDATES:\n"
        + "\n".join(f"- {n}" for n in names)
    )
    raw = _llm_json(PICK_NAME_PROMPT, user_content, max_tokens=200)
    if raw is None:
        return None
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if not isinstance(raw, dict):
        return None
    return _match_candidate_name(str(raw.get("name") or ""), names)


def pick_catalog_names_batch(
    jobs: list[dict],
) -> dict[int, Optional[str]]:
    """
    One LLM call for many shortlists.

    jobs: [{ "id": int, "spoken": str, "item_hint": str, "candidates": [str, ...] }, ...]
    Returns: { id: exact_candidate_or_None }
    """
    out: dict[int, Optional[str]] = {}
    need: list[dict] = []

    for job in jobs:
        jid = int(job["id"])
        names = _dedupe_names(job.get("candidates") or [])
        if not names:
            out[jid] = None
            continue
        if len(names) == 1:
            out[jid] = names[0]
            continue
        need.append(
            {
                "id": jid,
                "spoken": job.get("spoken") or "",
                "item_hint": job.get("item_hint") or "",
                "candidates": names,
            }
        )

    if not need:
        return out

    blocks = []
    for job in need:
        blocks.append(
            f"LINE id={job['id']}\n"
            f"Spoken/typed: {job['spoken'] or job['item_hint']}\n"
            f"Item hint: {job['item_hint'] or job['spoken']}\n"
            f"CANDIDATES:\n"
            + "\n".join(f"- {n}" for n in job["candidates"])
        )
    user_content = "\n\n".join(blocks)
    raw = _llm_json(PICK_NAMES_BATCH_PROMPT, user_content, max_tokens=800)

    by_id_candidates = {job["id"]: job["candidates"] for job in need}
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        for job in need:
            out[job["id"]] = None
        return out

    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            jid = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        names = by_id_candidates.get(jid) or []
        out[jid] = _match_candidate_name(str(row.get("name") or ""), names)

    for job in need:
        out.setdefault(job["id"], None)
    return out


def warm_up_llm() -> None:
    """Cheap request so TLS/DNS are ready before the first real order."""
    if os.getenv("GROQ_API_KEY"):
        _groq_chat("Reply with []", "ping", temperature=0, max_tokens=20)


_PARSE_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_PARSE_CACHE_MAX = 128


def parse_order(text: str, force: bool = False) -> dict:
    """
    Try Groq → Gemini → RapidFuzz in order.
    Returns: { "results": [...], "mode": "groq|gemini|fuzzy" }
    Successful LLM answers are cached (repeat/identical phrases are instant).
    force=True re-asks with "this is definitely an order, don't return []"
    (used when the first answer was empty but a pre-check says it's an order).
    """
    key = ("!" if force else "") + (text or "").strip()
    cached = _PARSE_CACHE.get(key)
    if cached is not None:
        _PARSE_CACHE.move_to_end(key)
        return {"results": [dict(r) for r in cached["results"]], "mode": cached["mode"]}

    out = None
    if os.getenv("GROQ_API_KEY"):
        try:
            out = {"results": parse_with_groq(text, force), "mode": "groq"}
        except Exception:
            out = None

    if out is None and os.getenv("GEMINI_API_KEY"):
        try:
            out = {"results": parse_with_gemini(text, force), "mode": "gemini"}
        except Exception:
            out = None

    if out is None:
        return {"results": parse_with_fuzzy(text), "mode": "fuzzy"}

    if not out["results"] and not force:
        return out  # don't cache "[]": the rescue pass may find an order
    _PARSE_CACHE[key] = {"results": [dict(r) for r in out["results"]], "mode": out["mode"]}
    while len(_PARSE_CACHE) > _PARSE_CACHE_MAX:
        _PARSE_CACHE.popitem(last=False)
    return out
