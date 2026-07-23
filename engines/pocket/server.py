"""OpenAI-compatible HTTP wrapper around Kyutai's Pocket TTS.

Pocket TTS ships a Python API and a demo web UI, but no OpenAI-shaped endpoint.
This exposes `/v1/audio/speech` (and a streaming variant) so the gateway can talk
to all three engines through the same contract.
"""

from __future__ import annotations

import io
import logging
import os
import struct
import threading
import wave
from contextlib import asynccontextmanager

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from pocket_tts import TTSModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pocket")

LANGUAGE = os.getenv("POCKET_LANGUAGE", "spanish_24l")
DEFAULT_VOICE = os.getenv("POCKET_VOICE", "lola")
QUANTIZE = os.getenv("POCKET_QUANTIZE", "false").lower() in ("1", "true", "yes")

# Language of each built-in voice, for grouping in the UI. Names come from
# pocket_tts.utils.utils._ORIGINS_OF_PREDEFINED_VOICES.
VOICE_LANGUAGES = {
    "lola": "es",
    "rafael": "es",
    "giovanni": "it",
    "juergen": "de",
    "estelle": "fr",
}

_model: TTSModel | None = None
_states: dict[str, dict] = {}
# generate_audio is documented as not thread-safe; one model instance means one
# generation at a time.
_lock = threading.Lock()


def _voice_names() -> list[str]:
    try:
        from pocket_tts.utils.utils import _ORIGINS_OF_PREDEFINED_VOICES

        return sorted(_ORIGINS_OF_PREDEFINED_VOICES)
    except Exception:  # pragma: no cover - private API moved
        log.warning("Could not read the built-in voice catalog, falling back")
        return sorted({DEFAULT_VOICE, "alba", "lola", "giovanni", "juergen", "estelle"})


def _state_for(voice: str) -> dict:
    if voice not in _states:
        log.info("Loading voice %s", voice)
        _states[voice] = _model.get_state_for_audio_prompt(voice)
    return _states[voice]


def _to_pcm16(audio: torch.Tensor) -> bytes:
    samples = audio.detach().to(torch.float32).cpu().numpy().reshape(-1)
    samples = np.clip(samples, -1.0, 1.0)
    return (samples * 32767.0).astype("<i2").tobytes()


def _wav(audio: torch.Tensor, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(_to_pcm16(audio))
    return buf.getvalue()


def _streaming_wav_header(sample_rate: int) -> bytes:
    """RIFF header with placeholder sizes, for audio of unknown length.

    Players read until the connection closes; the oversized `data` chunk keeps
    them from stopping at the declared length.
    """
    return (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", 0xFFFFFFFF - 36)
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    log.info("Loading Pocket TTS (language=%s, quantize=%s)", LANGUAGE, QUANTIZE)
    _model = TTSModel.load_model(language=LANGUAGE, quantize=QUANTIZE)
    log.info("Model ready on %s at %d Hz", _model.device, _model.sample_rate)
    _state_for(DEFAULT_VOICE)  # warm the default voice so the first request is fast
    yield


app = FastAPI(title="Pocket TTS", lifespan=lifespan)


class SpeechRequest(BaseModel):
    input: str = Field(min_length=1)
    voice: str | None = None
    model: str | None = None  # accepted and ignored, for OpenAI client compatibility
    response_format: str | None = None


@app.get("/health")
def health():
    ready = _model is not None
    return {
        "status": "ok" if ready else "loading",
        "language": LANGUAGE,
        "sample_rate": _model.sample_rate if ready else None,
    }


@app.get("/voices")
def voices():
    return {
        "default": DEFAULT_VOICE,
        "language": LANGUAGE,
        "voices": [
            {"id": name, "language": VOICE_LANGUAGES.get(name, "en")}
            for name in _voice_names()
        ],
    }


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest):
    if _model is None:
        raise HTTPException(503, "Model still loading")
    voice = req.voice or DEFAULT_VOICE
    try:
        with _lock:
            audio = _model.generate_audio(_state_for(voice), req.input)
    except Exception as exc:
        log.exception("Generation failed")
        raise HTTPException(500, f"Generation failed: {exc}") from exc
    return Response(_wav(audio, _model.sample_rate), media_type="audio/wav")


@app.post("/v1/audio/speech/stream")
def speech_stream(req: SpeechRequest):
    if _model is None:
        raise HTTPException(503, "Model still loading")
    voice = req.voice or DEFAULT_VOICE
    sample_rate = _model.sample_rate

    def chunks():
        yield _streaming_wav_header(sample_rate)
        with _lock:
            for chunk in _model.generate_audio_stream(_state_for(voice), req.input):
                yield _to_pcm16(chunk)

    return StreamingResponse(chunks(), media_type="audio/wav")
