"""Optional Groq Whisper speech-to-text.

This module is deliberately independent from the order parser: it only turns
audio into text, which then enters the existing parse-order flow.
"""

from __future__ import annotations

import os

from groq import Groq


DEFAULT_WHISPER_MODEL = "whisper-large-v3"


class TranscriptionUnavailable(RuntimeError):
    """Raised for a configuration or provider failure safe to show to the UI."""


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
    kwargs = {
        "file": (filename, audio),
        "model": model,
        "response_format": "json",
        "temperature": 0.0,
        "prompt": (
            "A wholesale motorcycle spare-parts order in Pakistani English, "
            "Urdu, or mixed Urdu and English. Preserve quantities, model names, "
            "item codes, and separate item phrases accurately."
        ),
        "timeout": float(os.getenv("GROQ_WHISPER_TIMEOUT_SECONDS", "30")),
    }
    if language in {"en", "ur"}:
        kwargs["language"] = language

    try:
        result = Groq(api_key=key).audio.transcriptions.create(**kwargs)
    except Exception as exc:
        # Do not expose provider internals or the API key to the browser.
        status = getattr(exc, "status_code", None)
        if status == 429:
            message = "Whisper rate limit reached. Retry shortly or use Browser voice."
        elif status in {401, 403}:
            message = "Groq rejected the API key. Check it in Settings."
        else:
            message = "Whisper transcription failed. Retry or use Browser voice."
        raise TranscriptionUnavailable(message) from exc

    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise TranscriptionUnavailable("No speech was detected in the recording.")
    return {"text": text, "model": model}
