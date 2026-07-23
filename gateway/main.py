"""TTS Hub gateway: one text box, three engines.

Normalises three different local TTS APIs behind a single contract so the UI
(and any client) can switch engines without knowing their quirks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway")

STATIC = Path(__file__).parent / "static"

POCKET_URL = os.getenv("POCKET_URL", "http://pocket:8000")
KOKORO_URL = os.getenv("KOKORO_URL", "http://kokoro:8880")
CHATTERBOX_URL = os.getenv("CHATTERBOX_URL", "http://chatterbox:4123")

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
