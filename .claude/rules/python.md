---
paths:
  - "gateway/**/*.py"
  - "engines/**/*.py"
---

# Python Rules — FastAPI services

## Stack

Python 3.12 · FastAPI · uvicorn · httpx (async) · pydantic v2. No ORM, no
database, no test framework wired in yet.

## Patterns in use

- `from __future__ import annotations` at the top of every module.
- Config read from `os.getenv` at module level, with a literal default that
  works standalone. Never require an env var to boot.
- Models are pydantic `BaseModel` with `Field(min_length=1)` for required text.
- Heavy models load in a FastAPI `lifespan` context manager, never on first
  request — the container should be unhealthy while loading, not slow.
- Module-level singletons (`_model`, `_JOBS`, `_states`) prefixed with `_`.

## Async rules

- All outbound HTTP uses `httpx.AsyncClient` with the module `TIMEOUT`.
- Never call a blocking model API from an async route without a lock; both
  PocketTTS and faster-whisper are documented as not thread-safe.
- For streaming responses, `StreamingResponse` over an async generator. Close
  the client in a `finally` inside the generator, not outside it — the response
  outlives the calling function.

## Error handling

- Raise `HTTPException` with a message the UI can show a user directly.
- When proxying, prefix the upstream error with the engine name and truncate:
  `raise HTTPException(status, f"{cfg['name']}: {response.text[:500]}")`.
- Third-party endpoints that may not exist (`/voices` on old Chatterbox tags)
  are best-effort: catch, log a warning, return a sane default. Do not let an
  optional feature mark a healthy service as offline.

## Audio handling

- WAV in, WAV out. Mono, 16-bit PCM.
- Always run third-party WAV bytes through `_fix_wav_sizes` before `wave.open`.
- Read the sample rate from the header. Never hardcode 24000.
- For streams of unknown length, emit a RIFF header with placeholder sizes
  (`_open_wav_header`) and let the connection close signal the end.

## Comments

Comment the *why*, especially where the code works around a third-party quirk.
Those comments are the only record of why the code looks strange:

```python
# Kokoro answers complete requests with a streaming-style header whose sizes
# are 0xFFFFFFFF. Browsers then report an ~89000 s duration and refuse to seek.
```

Do not comment what the line obviously does.
