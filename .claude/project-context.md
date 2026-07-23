---
orchestration-stack: "subagent-pool v8.1 · arquitec-dev-ia v5.0"
documented-at: "2026-07-23T13:30:14Z"
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

Progressive (segment-by-segment) synthesis ships alongside the original
one-shot path: `POST /api/segment` (preview split), `POST /api/speak/prepare`
(register a job), `GET /api/speak/stream/{job_id}` (chunked WAV, plays as it
generates) and `GET /api/speak/file/{job_id}` (assembled download). See
"Recent Work" below for details and open issues.

## God Nodes (High-Risk Files)

- `gateway/main.py` — ~772 lines, ~35 functions — every HTTP route, all four
  engine adapters, all WAV manipulation and the LLM bridge. Changes impact:
  every service, the UI, and all external API consumers.
- `docker-compose.yml` — ~129 lines — wires all 5 services, ports, env vars,
  GPU reservation, healthchecks. Changes impact: the entire stack.
- `gateway/static/index.html` — ~890 lines — single-file UI (design-system CSS + markup + JS)
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

## Recent Work (as of documented-at)

Progressive segment-by-segment synthesis is implemented, reviewed and
measured. `split_text()` cuts on sentence boundaries, merges short pieces,
hard-splits long ones, and a `SEGMENT_GAP_MS` silence is inserted between
segments. The UI's "Progresiva" checkbox (default checked) points `<audio>`
straight at `GET /api/speak/stream/{job_id}` — no blob buffering — and falls
back to one full request per segment for engines without native streaming.
`/api/speak` is unchanged and still backs the conversation tab.

Measured on an 851-char Spanish paragraph (6 segments): PocketTTS reaches
first audio in 0.243 s progressive vs 18.63 s baseline (76.7× sooner); Kokoro
in 1.857 s vs 17.02 s (9.2× sooner). Full table and the curl-caveat about
`time_starttransfer` being invalid for this measurement live in AGENTS.md.

One issue is open, not resolved:

1. **MAJOR** — `engines/pocket/server.py`'s `/v1/audio/speech/stream` holds a
   `threading.Lock` across a sync generator; a client disconnect does not
   stop generation, so it stalls subsequent requests. Fires under normal
   progressive-playback use (user hits generate again mid-stream).

One is diagnosed and closed as accepted-by-design (not a bug):

- **PocketTTS progressive duration overshoot (+11.2%)** — traced to
  `pocket_tts`'s internal `split_into_best_sentences()` packer
  (`MAX_TOKEN_PER_CHUNK=50`, unrelated to the gateway's `SEGMENT_MAX_CHARS`),
  which pays ~240-850 ms of stochastic trailing silence-after-EOS per
  internal chunk; splitting text into more HTTP calls restarts that packer
  more times. Isolated measurement (no gateway involved): one call over a
  418-char text averaged 27.3 s vs 29.5 s as 4 independent calls. Both
  available fixes were rejected as unsafe (risk of clipping real audio, or
  reintroducing the buffering the streaming feature exists to avoid). Full
  diagnosis and the one deliberately-out-of-scope future option live in
  AGENTS.md.

Do not repeat the earlier "the gateway does not start" claim: that was never
an import-time failure — `_synthesise_segment` was a `NameError` raised only
when `GET /api/speak/stream/{job_id}` was called; uvicorn booted fine and
every other route worked throughout.

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
