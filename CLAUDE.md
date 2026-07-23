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

Progressive (segment-by-segment) synthesis is shipped and measured: PocketTTS
starts playback ~77× sooner, Kokoro ~9× sooner than the non-progressive path
(see AGENTS.md for the numbers and endpoints). One issue remains open — a
disconnect-safety bug in `engines/pocket/server.py`'s streaming lock. A
PocketTTS duration overshoot was also found, but is diagnosed and accepted.
