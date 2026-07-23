# TTS Hub

Local voice stack in Docker: three TTS engines, one STT engine, one gateway,
and a bridge to any OpenAI-compatible LLM. Nothing leaves the machine.

<!-- Thin entry point on purpose. Detail lives in AGENTS.md and .claude/rules/,
     which load automatically. Keep this file under ~40 lines. -->

@./AGENTS.md

## Quick reference

```bash
docker compose up -d                       # whole stack
docker compose up -d --build <service>     # after editing gateway/ or engines/
curl -s localhost:8600/api/engines | jq    # TTS engine status + voices
curl -s localhost:8600/api/services | jq   # STT + LLM status
```

UI at <http://localhost:8600>.

## Before you edit

- `gateway/main.py`, `docker-compose.yml` and `gateway/static/index.html` are
  god nodes. Surgical edits only — see `.claude/rules/conventions.md`.
- Engine capabilities are discovered at runtime, never hardcoded.
- Third-party WAV bytes always go through `_fix_wav_sizes` first.

## Current state

Progressive (segment-by-segment) synthesis is mid-refactor and **the gateway
does not start**: `produce()` in `speak_stream` still calls the removed
`_synthesise_segment()` instead of the new `_segment_chunks()` generator, and
the UI still buffers the whole response with `await res.blob()`.
