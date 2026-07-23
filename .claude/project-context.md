---
orchestration-stack: "subagent-pool v8.1 · arquitec-dev-ia v5.0"
documented-at: "2026-07-23T06:40:00Z"
graphify-graph: "missing"
graphify-nodes: 0
graphify-communities: 0
stack: "Python 3.12 · FastAPI · httpx · Docker Compose · vanilla JS"
language: "English (code) / Spanish (UI and docs)"
---

# Project Context — TTS Hub

<!-- graphify skipped deliberately: 15 tracked files, below the 20-file
     threshold where manual research is faster. Communities and god nodes
     below were derived by reading the module structure directly. -->

## Architecture Summary

Local voice stack orchestrated with Docker Compose. A FastAPI gateway (port
8600) serves a single-file web UI and normalises three text-to-speech engines
with incompatible APIs (PocketTTS, Kokoro, Chatterbox) plus a faster-whisper
STT service behind one uniform contract. A second UI tab closes a conversation
loop by bridging microphone → Whisper → any OpenAI-compatible LLM on the host
(LM Studio, Ollama) → the selected TTS engine. Two engines are built from this
repo; two are pinned third-party images. Nothing calls out to the network at
runtime except to reach the host's LLM server.

## God Nodes (High-Risk Files)

- `gateway/main.py` — ~737 lines, ~35 functions — every HTTP route, all four
  engine adapters, all WAV manipulation and the LLM bridge. Changes impact:
  every service, the UI, and all external API consumers.
- `docker-compose.yml` — ~129 lines — wires all 5 services, ports, env vars,
  GPU reservation, healthchecks. Changes impact: the entire stack.
- `gateway/static/index.html` — ~401 lines — single-file UI (markup + CSS + JS)
  consuming every gateway endpoint. No build step, no framework; a JS error
  blanks the page with no console trace for the user.

## Code Communities

| Community | Description | Key Files |
|---|---|---|
| Gateway / API | Routing, engine adapters, WAV helpers, segmentation, LLM bridge | `gateway/main.py`, `gateway/requirements.txt`, `gateway/Dockerfile` |
| UI | Single-file frontend, both tabs, mic capture, audio playback | `gateway/static/index.html` |
| TTS engine wrapper | OpenAI-shaped wrapper over the pocket-tts Python API, with native streaming | `engines/pocket/server.py`, `engines/pocket/Dockerfile` |
| STT engine wrapper | OpenAI-shaped wrapper over faster-whisper | `engines/stt/server.py`, `engines/stt/Dockerfile` |
| Infrastructure | Service wiring, ports, volumes, GPU, env surface | `docker-compose.yml`, `.env.example` |
| Vendored engines | No source here — pinned images only | Kokoro, Chatterbox |

## Cross-cutting Invariants

1. Every engine returns `audio/wav`, mono, 16-bit PCM. Sample rate is read from
   the header, never hardcoded (all happen to be 24 kHz today).
2. Kokoro returns complete responses with streaming RIFF sizes (`0xFFFFFFFF`);
   anything parsing engine output must call `_fix_wav_sizes` first.
3. Engine capabilities come from the engine's own `openapi.json`
   (`_supports_streaming`), never from a hardcoded flag.
4. PocketTTS and faster-whisper are not thread-safe; generation is serialised
   behind a lock in each wrapper.
5. The gateway holds no conversation state. Chat history lives in the browser.
   Only `_JOBS` is server state, TTL-pruned at 1800 s / 20 entries.

## Known Broken State (as of documented-at)

Progressive segment-by-segment synthesis is mid-refactor; **the gateway does
not currently start**:

- `produce()` inside `speak_stream` (~line 512) calls `_synthesise_segment()`,
  which was replaced by the async generator `_segment_chunks()` (~line 453).
- `gateway/static/index.html` has not been updated: `generate()` still does
  `await res.blob()`, so nothing plays progressively — not even PocketTTS,
  which has a native streaming endpoint.
- New, untested surface: `/api/segment`, `/api/speak/prepare`,
  `/api/speak/stream/{id}`, `/api/speak/file/{id}`, `split_text`,
  `_parse_wav_header`, `_open_wav_header`, `_decode_wav`, `_JOBS`.

Finishing this is the active task. Do not treat `gateway/main.py` as a working
baseline.

## Components Documented

| Component | AGENTS.md | CLAUDE.md | Rules |
|---|---|---|---|
| Root | ✅ | ✅ (thin, @includes AGENTS.md) | conventions, python, frontend, docker |

## Stack & Conventions

- **Code language**: English. **UI and README**: Spanish.
- **Runtime**: Python 3.12, FastAPI, uvicorn, httpx async, pydantic v2.
- **Frontend**: vanilla JS, single file, no build step, no CDN.
- **Testing**: none wired in. Verification is live curl against the running
  stack, checking audio duration/sample rate/RMS — not just status codes.
- **Commits**: conventional commits, English, body explains *why* and records
  third-party quirks discovered.
- **Docker**: yes, exclusively. Ports 8600/8601/8602/8880/4123, chosen around
  the host's Klipper, Fluidd, Ollama and LM Studio.
- **GPU**: single 6 GB RTX 3050 shared with the user's LLM. Only Chatterbox
  reserves it; everything else is CPU by design.

## Available Skills

None defined in this project yet.

| Candidate skill | Would trigger on |
|---|---|
| `tts-smoke-test` | "prueba el stack", "benchmark de motores" |
| `engine-add` | "añade un motor TTS", "registra un engine nuevo" |
