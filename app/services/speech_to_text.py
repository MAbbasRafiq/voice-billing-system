"""Local NVIDIA Parakeet TDT speech-to-text (ONNX / CPU).

Independent from the order parser: audio → text, then the existing parse-order flow.
Optimized for short English part-name utterances (quantity can be set in the UI).
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import numpy as np

DEFAULT_STT_MODEL = "nemo-parakeet-tdt-0.6b-v3"
DEFAULT_SAMPLE_RATE = 16000

_model = None
_model_lock = threading.Lock()


class TranscriptionUnavailable(RuntimeError):
    """Raised for a configuration or provider failure safe to show to the UI."""


def stt_model_name() -> str:
    return (
        os.getenv("STT_MODEL", "").strip()
        or os.getenv("PARAKEET_MODEL", "").strip()
        or DEFAULT_STT_MODEL
    )


# Back-compat for settings / status callers.
def whisper_model_name() -> str:
    return stt_model_name()


def _get_parakeet_model():
    """Load Parakeet ONNX once per process."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            import onnx_asr
        except ImportError as exc:
            raise TranscriptionUnavailable(
                "Local speech model is not installed. Run: pip install \"onnx-asr[cpu,hub]\""
            ) from exc

        name = stt_model_name()
        try:
            _model = onnx_asr.load_model(name)
        except Exception as exc:
            raise TranscriptionUnavailable(
                "Could not load Parakeet. Check STT_MODEL and that the model is cached."
            ) from exc
        return _model


def warm_up_stt() -> None:
    """Pre-load Parakeet on server startup so the first recording is faster."""
    try:
        _get_parakeet_model()
    except TranscriptionUnavailable:
        pass


def warm_up_whisper() -> None:
    """Alias kept for existing startup hooks."""
    warm_up_stt()


def _suffix_from_filename(filename: str) -> str:
    suffix = Path(filename or "recording.webm").suffix.lower()
    if suffix in {".webm", ".ogg", ".wav", ".mp3", ".mp4", ".m4a", ".opus"}:
        return suffix
    return ".webm"


def _decode_mono_16k(path: str) -> np.ndarray:
    """Decode any supported container to float32 mono @ 16 kHz for Parakeet."""
    try:
        import av
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "Audio decoder missing. Run: pip install \"av>=12,<16\""
        ) from exc

    resampler = av.audio.resampler.AudioResampler(
        format="flt",
        layout="mono",
        rate=DEFAULT_SAMPLE_RATE,
    )
    chunks: list[np.ndarray] = []
    try:
        with av.open(path, mode="r") as container:
            if not container.streams.audio:
                return np.zeros(0, dtype=np.float32)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    arr = out.to_ndarray().reshape(-1)
                    if arr.size:
                        chunks.append(arr.astype(np.float32, copy=False))
            for out in resampler.resample(None):
                arr = out.to_ndarray().reshape(-1)
                if arr.size:
                    chunks.append(arr.astype(np.float32, copy=False))
    except Exception as exc:
        raise TranscriptionUnavailable(
            "Could not decode the recording. Retry or use a different format."
        ) from exc

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def _result_text(result) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(result).strip()


def transcribe_audio(
    audio: bytes,
    filename: str,
    language: str | None = None,
) -> dict[str, str]:
    del language  # Parakeet auto-detects; shop voice is English part names
    if not audio:
        raise TranscriptionUnavailable("No audio was received.")

    model_name = stt_model_name()
    model = _get_parakeet_model()
    suffix = _suffix_from_filename(filename)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp_path = tmp.name

        waveform = _decode_mono_16k(tmp_path)
        if waveform.size == 0:
            raise TranscriptionUnavailable("No speech was detected in the recording.")

        result = model.recognize(waveform, sample_rate=DEFAULT_SAMPLE_RATE)
        text = _result_text(result)
    except TranscriptionUnavailable:
        raise
    except Exception as exc:
        raise TranscriptionUnavailable(
            "Local transcription failed. Retry or type the order."
        ) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not text:
        raise TranscriptionUnavailable("No speech was detected in the recording.")
    return {"text": text, "model": model_name}
