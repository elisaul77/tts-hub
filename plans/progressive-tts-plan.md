# Plan — Progressive segment-by-segment synthesis

Task: long texts must start playing on the first sentence instead of after the
whole passage.

Approved: 2026-07-23 · Mode: no pauses · Architecture: flat pyramid

## Corrections to the starting brief

- `_synthesise_segment` is a `NameError` at **call time**, not import time.
  uvicorn boots; only `GET /api/speak/stream/{job_id}` 500s. The docs saying
  "the gateway does not start" are imprecise — fix at closure.
- The running `tts-hub-gateway` container is **stale** (`/api/speak/prepare`
  → 404). The gateway has no bind mount; code is `COPY`'d. Any measurement
  before `docker compose up -d --build gateway` is meaningless.

## Resolved open questions

1. The existing `#stream` checkbox is **repurposed** as the progressive toggle
   ("Progresiva"), enabled for every online engine — the `_segment_chunks`
   fallback covers engines without native streaming. Not a second checkbox.
2. Default **checked**. An unchecked default would ship the exact bug this
   task fixes as the out-of-the-box experience.

## Phases

### Phase 1 — Fix `produce()` (backend)
Consume the `_segment_chunks()` generator protocol correctly so the streaming
route works. Single-function edit in `gateway/main.py` (~504-538).

Key invariants: one RIFF header for the whole job (first `fmt` only); silence
gap once per segment boundary, not per internal chunk; strictly sequential
segments (PocketTTS is not thread-safe); `native` resolved once via
`_supports_streaming`; yield each pcm chunk immediately; clean `break` on
mid-stream failure; `job["audio"]` byte-identical to what was streamed.

### Phase 2 — Progressive playback (UI)
`<audio>.src` pointed straight at the streaming URL. New `generateProgressive()`
alongside the untouched `synthesize()` (the chat tab keeps using the latter).
Segment count in the status line, download link via `/api/speak/file/{id}`
revealed on `ended`.

### Phase 3 — Live verification
Rebuild first, then measure TTFB vs total for pocket and kokoro, progressive
vs baseline, on a long multi-sentence Spanish paragraph.

Expected: progressive TTFB ≈ first-segment time; baseline TTFB ≈ TOTAL; totals
roughly comparable between modes (progressive starts sooner, is not faster).

## Out of scope

Tests (deferred by user), new dependencies, `engines/*`, `docker-compose.yml`,
any change to `/api/speak` behaviour.
