"""AI order parser: Groq → Gemini → RapidFuzz."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """
You are a billing assistant for a Pakistani motorcycle spare parts shop.
The admin will speak an order in English or mixed Urdu/English.
Your job is to extract each item mentioned and return ONLY a JSON array.

Rules:
- Extract item name, model/variant if mentioned, and quantity
- If model is not mentioned or is ambiguous, set model to null
- Set confidence to "exact" if both item and model are clear, else "ambiguous"
- Do not guess or infer a model — only set it if clearly spoken
- Return raw JSON only, no explanation, no markdown fences

Output format:
[{ "spoken": "original phrase", "item": "normalized item name",
   "model": "MODEL or null", "qty": number, "confidence": "exact|ambiguous" }]
"""

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")


def _strip_json(text: str) -> Any:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Find first JSON array if prose sneaks in
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
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


def parse_with_groq(text: str) -> list[dict]:
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        max_tokens=1000,
    )
    content = response.choices[0].message.content
    return _normalize_results(_strip_json(content))


def parse_with_gemini(text: str) -> list[dict]:
    import google.generativeai as genai

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel(GEMINI_MODEL)
    result = model.generate_content(SYSTEM_PROMPT + "\n\nOrder: " + text)
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


def parse_order(text: str) -> dict:
    """
    Try Groq → Gemini → RapidFuzz in order.
    Returns: { "results": [...], "mode": "groq|gemini|fuzzy" }
    """
    if os.getenv("GROQ_API_KEY"):
        try:
            return {"results": parse_with_groq(text), "mode": "groq"}
        except Exception:
            pass

    if os.getenv("GEMINI_API_KEY"):
        try:
            return {"results": parse_with_gemini(text), "mode": "gemini"}
        except Exception:
            pass

    return {"results": parse_with_fuzzy(text), "mode": "fuzzy"}
