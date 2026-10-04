"""Optional Groq Whisper speech-to-text.

This module is deliberately independent from the order parser: it only turns
audio into text, which then enters the existing parse-order flow.
"""

from __future__ import annotations

import os
from functools import lru_cache

from groq import Groq

from app.database.queries import get_all_items_for_fuzzy, items_version


DEFAULT_WHISPER_MODEL = "whisper-large-v3"
# Groq Whisper rejects prompts longer than this (API: 896).
MAX_WHISPER_PROMPT_CHARS = 896

_BASE_PROMPT = (
    "Pakistani motorcycle spare-parts order. "
    "Part names in English catalog form "
    "(air filter, chain kit, back light complete, bearing, cdi unit). "
    "Quantities may be Urdu, English, Roman, or digits "
    "(دو, teen, 2). "
    "Preserve quantities, English names, models (CD70, CG125)."
)


class TranscriptionUnavailable(RuntimeError):
    """Raised for a configuration or provider failure safe to show to the UI."""


@lru_cache(maxsize=4)
def _catalog_hotwords(version: int, budget: int) -> str:
    """Short list of frequent English catalog names + models for Whisper bias."""
    del version  # cache key only
    if budget < 40:
        return ""

    items = get_all_items_for_fuzzy()
    name_counts: dict[str, int] = {}
    models: set[str] = set()
    for it in items:
        name = (it.get("name") or "").strip()
        if name and name != "-":
            stem = name.split("(")[0].strip()
            if 2 <= len(stem) <= 40:
                name_counts[stem] = name_counts.get(stem, 0) + 1
        model = (it.get("model") or "").strip()
        if model and any(c.isdigit() for c in model):
            models.add(model.split()[0][:24])

    top_names = sorted(name_counts, key=lambda n: (-name_counts[n], n))
    top_models = sorted(models)

    parts: list[str] = []
    prefix = "Parts: "
    used = len(prefix)
    for name in top_names:
        piece = (", " if parts else "") + name
        if used + len(piece) > budget // 2:
            break
        parts.append(name)
        used += len(piece)

    model_bits: list[str] = []
    mprefix = " Models: "
    mused = len(mprefix)
    model_budget = budget - used - len(mprefix) - 1
    for model in top_models:
        piece = (", " if model_bits else "") + model
        if mused + len(piece) > max(0, model_budget):
            break
        model_bits.append(model)
        mused += len(piece)

    out = ""
    if parts:
        out += prefix + ", ".join(parts) + "."
    if model_bits:
        out += mprefix + ", ".join(model_bits) + "."
    return out[:budget]


def _whisper_prompt() -> str:
    base = _BASE_PROMPT
    budget = MAX_WHISPER_PROMPT_CHARS - len(base) - 1
    try:
        hot = _catalog_hotwords(items_version(), max(0, budget))
    except Exception:
        hot = ""
    if hot:
        return f"{base} {hot}"[:MAX_WHISPER_PROMPT_CHARS]
    return base[:MAX_WHISPER_PROMPT_CHARS]


def transcribe_audio(
    audio: bytes,
    filename: str,
    language: str | None = None,
) -> dict[str, str]:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise TranscriptionUnavailable(
            "Groq API key is not configured. Add it in Settings or use Browser voice."
        )
    if not audio:
        raise TranscriptionUnavailable("No audio was received.")

    model = os.getenv("GROQ_WHISPER_MODEL", DEFAULT_WHISPER_MODEL).strip()
    client = Groq(
        api_key=key,
        timeout=float(os.getenv("GROQ_WHISPER_TIMEOUT_SECONDS", "30")),
    )
    kwargs = {
        "file": (filename, audio),
        "model": model,
        "response_format": "json",
        "temperature": 0.0,
        "prompt": _whisper_prompt(),
    }
    if language in {"en", "ur"}:
        kwargs["language"] = language

    try:
        result = client.audio.transcriptions.create(**kwargs)
    except Exception as exc:
        # Do not expose provider internals or the API key to the browser.
        status = getattr(exc, "status_code", None)
        if status == 429:
            message = "Whisper rate limit reached. Retry shortly or use Browser voice."
        elif status in {401, 403}:
            message = "Groq rejected the API key. Check it in Settings."
        elif status == 400:
            message = "Whisper rejected the recording. Retry or use Browser voice."
        else:
            message = "Whisper transcription failed. Retry or use Browser voice."
        raise TranscriptionUnavailable(message) from exc

    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise TranscriptionUnavailable("No speech was detected in the recording.")
    return {"text": text, "model": model}
