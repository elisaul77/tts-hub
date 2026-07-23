"""TTS Hub gateway: one text box, three engines.

Normalises three different local TTS APIs behind a single contract so the UI
(and any client) can switch engines without knowing their quirks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

STATIC = Path(__file__).parent / "static"

POCKET_URL = os.getenv("POCKET_URL", "http://pocket:8000")
KOKORO_URL = os.getenv("KOKORO_URL", "http://kokoro:8880")
CHATTERBOX_URL = os.getenv("CHATTERBOX_URL", "http://chatterbox:4123")
STT_URL = os.getenv("STT_URL", "http://stt:8000")

# Any OpenAI-compatible server: LM Studio (1234), Ollama (11434), llama.cpp...
LLM_URL = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Eres un asistente de voz. Responde en español, de forma breve y natural, "
    "como en una conversación hablada. Tu respuesta se va a leer en voz alta, "
    "así que nunca uses markdown, listas ni emojis, y escribe las cifras con "
    "palabras (trescientos mil, no 300.000).",
)

# Generation on CPU can be slow for long text; be generous.
TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=30.0, pool=5.0)

ENGINES = {
    "pocket": {
        "name": "PocketTTS",
        "tagline": "Kyutai · 100M · CPU",
        "description": "Español nativo, ~200 ms al primer chunk. El más rápido.",
        "url": POCKET_URL,
        "streaming": True,
        "device": "CPU",
    },
    "kokoro": {
        "name": "Kokoro",
        "tagline": "82M · CPU · 8 idiomas",
        "description": "54 voces multilingües. Español latino.",
        "url": KOKORO_URL,
        "streaming": False,
        "device": "CPU",
    },
    "chatterbox": {
        "name": "Chatterbox",
        "tagline": "Resemble AI · 0.5B · GPU",
        "description": "Máxima calidad y clonación de voz. 22 idiomas.",
        "url": CHATTERBOX_URL,
        "streaming": True,
        "device": "GPU",
    },
}

app = FastAPI(title="TTS Hub")


class SpeakRequest(BaseModel):
    engine: str
    text: str = Field(min_length=1)
    voice: str | None = None
    speed: float = 1.0
    stream: bool = False


# --------------------------------------------------------------------------
# Per-engine adapters
# --------------------------------------------------------------------------


async def _voices_pocket(client: httpx.AsyncClient, base: str) -> list[dict]:
    data = (await client.get(f"{base}/voices", timeout=10.0)).json()
    return data.get("voices", [])


async def _voices_kokoro(client: httpx.AsyncClient, base: str) -> list[dict]:
    data = (await client.get(f"{base}/v1/audio/voices", timeout=10.0)).json()
    raw = data.get("voices", data if isinstance(data, list) else [])
    # Kokoro encodes language in the first letter of the voice id: a=en-US,
    # b=en-GB, e=es, f=fr, h=hi, i=it, j=ja, p=pt-BR, z=zh.
    prefixes = {
        "a": "en",
        "b": "en",
        "e": "es",
        "f": "fr",
        "h": "hi",
        "i": "it",
        "j": "ja",
        "p": "pt",
        "z": "zh",
    }
    out = []
    for item in raw:
        vid = item if isinstance(item, str) else item.get("id") or item.get("name", "")
        if vid:
            out.append({"id": vid, "language": prefixes.get(vid[:1], "en")})
    return sorted(out, key=lambda v: (v["language"] != "es", v["id"]))


async def _voices_chatterbox(client: httpx.AsyncClient, base: str) -> list[dict]:
    # The built-in sample is always there. The named voice library only exists
    # in newer builds, so treat it as a bonus rather than a requirement.
    out = [{"id": "default", "language": "auto"}]
    try:
        response = await client.get(f"{base}/voices", timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return out
    raw = data.get("voices", data if isinstance(data, list) else [])
    for item in raw:
        if isinstance(item, str):
            out.append({"id": item, "language": "auto"})
        else:
            name = item.get("name") or item.get("voice_name") or item.get("id")
            if name:
                out.append({"id": name, "language": item.get("language", "auto")})
    return out


VOICE_LOADERS = {
    "pocket": _voices_pocket,
    "kokoro": _voices_kokoro,
    "chatterbox": _voices_chatterbox,
}


def _payload(engine: str, req: SpeakRequest) -> dict:
    if engine == "kokoro":
        body = {
            "model": "kokoro",
            "input": req.text,
            "voice": req.voice or "ef_dora",
            "response_format": "wav",
            "speed": req.speed,
        }
        return body
    body: dict = {"input": req.text}
    if req.voice and req.voice != "default":
        body["voice"] = req.voice
    return body


def _fix_wav_sizes(data: bytes) -> bytes:
    """Rewrite RIFF/data chunk sizes to match the real payload.

    Kokoro answers complete requests with a streaming-style header whose sizes
    are 0xFFFFFFFF. Browsers then report an ~89000 s duration and refuse to
    seek. Since we already have the whole file here, patch the sizes.
    """
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if chunk_id == b"data":
            real = len(data) - (offset + 8)
            if chunk_size == real:
                return data
            patched = bytearray(data)
            patched[4:8] = (len(data) - 8).to_bytes(4, "little")
            patched[offset + 4 : offset + 8] = real.to_bytes(4, "little")
            return bytes(patched)
        offset += 8 + chunk_size + (chunk_size & 1)
    return data


STREAM_PATH = "/v1/audio/speech/stream"


async def _supports_streaming(client: httpx.AsyncClient, base: str, fallback: bool) -> bool:
    """Ask the engine itself instead of trusting a hardcoded flag.

    Chatterbox only grew a streaming endpoint in recent builds, so which image
    tag you happen to be running decides the answer.
    """
    try:
        response = await client.get(f"{base}/openapi.json", timeout=8.0)
        response.raise_for_status()
        return STREAM_PATH in response.json().get("paths", {})
    except Exception:
        return fallback


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@app.get("/api/engines")
async def list_engines():
    async with httpx.AsyncClient() as client:

        async def probe(key: str, cfg: dict) -> dict:
            entry = {k: v for k, v in cfg.items() if k != "url"}
            entry["id"] = key
            base = cfg["url"]
            try:
                response = await client.get(f"{base}/health", timeout=8.0)
                response.raise_for_status()
            except Exception as exc:
                entry.update(status="offline", error=str(exc), voices=[], streaming=False)
                return entry
            entry["status"] = "online"
            entry["streaming"] = await _supports_streaming(client, base, cfg["streaming"])
            try:
                entry["voices"] = await VOICE_LOADERS[key](client, base)
            except Exception as exc:
                log.warning("Could not list %s voices: %s", key, exc)
                entry["voices"] = []
            return entry

        return await asyncio.gather(*(probe(k, v) for k, v in ENGINES.items()))


@app.post("/api/speak")
async def speak(req: SpeakRequest):
    cfg = ENGINES.get(req.engine)
    if cfg is None:
        raise HTTPException(400, f"Unknown engine: {req.engine}")

    streaming = False
    if req.stream:
        async with httpx.AsyncClient() as probe_client:
            streaming = await _supports_streaming(probe_client, cfg["url"], cfg["streaming"])

    url = cfg["url"] + (STREAM_PATH if streaming else "/v1/audio/speech")
    body = _payload(req.engine, req)
    started = time.perf_counter()

    if streaming:
        client = httpx.AsyncClient(timeout=TIMEOUT)
        request = client.build_request("POST", url, json=body)
        try:
            response = await client.send(request, stream=True)
        except Exception as exc:
            await client.aclose()
            raise HTTPException(502, f"{cfg['name']} unreachable: {exc}") from exc
        if response.status_code >= 400:
            detail = (await response.aread()).decode("utf-8", "replace")[:500]
            await response.aclose()
            await client.aclose()
            raise HTTPException(response.status_code, f"{cfg['name']}: {detail}")

        async def relay():
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(relay(), media_type="audio/wav")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(url, json=body)
        except Exception as exc:
            raise HTTPException(502, f"{cfg['name']} unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            f"{cfg['name']}: {response.text[:500]}",
        )

    audio = _fix_wav_sizes(response.content)
    elapsed = time.perf_counter() - started
    log.info("%s generated %d bytes in %.2fs", req.engine, len(audio), elapsed)
    return Response(
        audio,
        media_type="audio/wav",
        headers={"X-Generation-Seconds": f"{elapsed:.2f}"},
    )


# --------------------------------------------------------------------------
# Conversation loop: microphone -> STT -> LLM -> TTS
# --------------------------------------------------------------------------


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


async def _resolve_llm_model(client: httpx.AsyncClient) -> str:
    """Use whatever model the server has loaded unless one was configured.

    LM Studio serves a single loaded model but still wants the field populated;
    asking it beats hardcoding a name that changes every time you swap models.
    """
    if LLM_MODEL:
        return LLM_MODEL
    try:
        response = await client.get(
            f"{LLM_URL}/models",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        if data:
            return data[0].get("id", "local-model")
    except Exception as exc:
        log.warning("Could not list LLM models: %s", exc)
    return "local-model"


async def _transcribe(audio: bytes, filename: str, language: str | None) -> dict:
    files = {"file": (filename or "audio.webm", audio, "application/octet-stream")}
    data = {"language": language} if language else {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(
                f"{STT_URL}/v1/audio/transcriptions", files=files, data=data
            )
        except Exception as exc:
            raise HTTPException(502, f"STT unreachable: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"STT: {response.text[:500]}")
    return response.json()


async def _complete(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        model = await _resolve_llm_model(client)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            "temperature": 0.7,
        }
        try:
            response = await client.post(
                f"{LLM_URL}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            )
        except Exception as exc:
            raise HTTPException(
                502,
                f"LLM unreachable at {LLM_URL}. Is LM Studio serving on the "
                f"local network? ({exc})",
            ) from exc
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"LLM: {response.text[:500]}")
    return response.json()["choices"][0]["message"]["content"].strip()


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str | None = Form(None)):
    return await _transcribe(await file.read(), file.filename or "audio.webm", language)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    reply = await _complete([m.model_dump() for m in req.messages])
    return {"reply": reply}


@app.post("/api/converse")
async def converse(
    file: UploadFile = File(...),
    history: str = Form("[]"),
    language: str | None = Form(None),
):
    """One turn: audio in, transcript and reply text out.

    The reply is not synthesised here — the client posts it to /api/speak with
    whichever engine and voice it has selected, and gets to show the text while
    the audio is still generating.
    """
    started = time.perf_counter()
    heard = await _transcribe(await file.read(), file.filename or "audio.webm", language)
    user_text = heard.get("text", "").strip()
    if not user_text:
        raise HTTPException(422, "No se entendió nada en el audio")

    try:
        messages = json.loads(history)
        if not isinstance(messages, list):
            raise ValueError
    except Exception:
        messages = []
    messages.append({"role": "user", "content": user_text})

    reply = await _complete(messages)
    log.info("Turn completed in %.2fs", time.perf_counter() - started)
    return {"user_text": user_text, "reply_text": reply}


@app.get("/api/services")
async def services():
    """Status of the two pieces the conversation loop needs beyond TTS."""

    async def probe_stt(client: httpx.AsyncClient) -> dict:
        try:
            response = await client.get(f"{STT_URL}/health", timeout=8.0)
            response.raise_for_status()
            # status last: the engine reports its own "ok", which would
            # otherwise overwrite the value the UI checks for.
            return {**response.json(), "status": "online"}
        except Exception as exc:
            return {"status": "offline", "error": str(exc)}

    async def probe_llm(client: httpx.AsyncClient) -> dict:
        # _resolve_llm_model falls back to a placeholder name, so it cannot tell
        # us whether the server is up. Hit /models directly.
        try:
            response = await client.get(
                f"{LLM_URL}/models",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                timeout=8.0,
            )
            response.raise_for_status()
            data = response.json().get("data", [])
        except Exception as exc:
            return {"status": "offline", "url": LLM_URL, "error": str(exc)}
        return {
            "status": "online",
            "url": LLM_URL,
            "model": LLM_MODEL or (data[0].get("id") if data else "local-model"),
            "available": [m.get("id") for m in data][:20],
        }

    async with httpx.AsyncClient() as client:
        stt, llm = await asyncio.gather(probe_stt(client), probe_llm(client))
    return {"stt": stt, "llm": llm}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
