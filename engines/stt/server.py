"""OpenAI-compatible speech-to-text on top of faster-whisper.

Deliberately CPU-first: the GPU is usually busy with the LLM and with
Chatterbox, and `small` + int8 transcribes a few seconds of speech well under
a second on a modern multi-core CPU.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stt")

MODEL_SIZE = os.getenv("STT_MODEL", "small")
DEVICE = os.getenv("STT_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "int8")
LANGUAGE = os.getenv("STT_LANGUAGE", "es") or None
BEAM_SIZE = int(os.getenv("STT_BEAM_SIZE", "1"))

_model: WhisperModel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    log.info("Loading faster-whisper %s (%s, %s)", MODEL_SIZE, DEVICE, COMPUTE_TYPE)
    _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    log.info("Model ready")
    yield


app = FastAPI(title="Whisper STT", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok" if _model is not None else "loading",
        "model": MODEL_SIZE,
        "device": DEVICE,
        "language": LANGUAGE or "auto",
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    model: str | None = Form(None),  # accepted and ignored, for OpenAI clients
):
    if _model is None:
        raise HTTPException(503, "Model still loading")

    payload = await file.read()
    if not payload:
        raise HTTPException(400, "Empty audio")

    # faster-whisper decodes through PyAV, so webm/opus straight from the
    # browser's MediaRecorder works without shelling out to ffmpeg.
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(payload)
        tmp_path = tmp.name

    try:
        segments, info = _model.transcribe(
            tmp_path,
            language=language or LANGUAGE,
            beam_size=BEAM_SIZE,
            vad_filter=True,
        )
        text = "".join(segment.text for segment in segments).strip()
    except Exception as exc:
        log.exception("Transcription failed")
        raise HTTPException(500, f"Transcription failed: {exc}") from exc
    finally:
        os.unlink(tmp_path)

    log.info("Transcribed %.1fs of %s audio", info.duration, info.language)
    return {"text": text, "language": info.language, "duration": info.duration}
