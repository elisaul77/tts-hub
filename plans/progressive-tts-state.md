## State — last updated: Phase 1 APPROVED

Plan file: plans/progressive-tts-plan.md
Mode: no pauses · flat pyramid

Completed:
- Phase 0 — plan drafted (PLAN_READY, 3 phases)
- Phase 1 — `produce()` consumes `_segment_chunks` · APPROVED
- Phase 2 — progressive UI · APPROVED

In flight:
- Phase 3 — live verification (rebuild + TTFB vs total, pocket and kokoro)

Current: Phase 3 → then docs correction → then commit and push.

Conventions: lang=English (code) / Spanish (UI), stack=Python 3.12 · FastAPI ·
httpx async · vanilla JS single file.

## Verified invariants (both reviews)
- Exactly one RIFF header per job; later `fmt` events compare-and-log only.
- Gap silence once per segment boundary, not per internal engine chunk
  (traced against a 2-segment job where segment 2 yields 5 native chunks).
- Chunks yielded immediately — no segment-level buffering, which would have
  passed every functional test while silently destroying the TTFB benefit.
- `except Exception` not `BaseException`, so `GeneratorExit`/`CancelledError`
  still propagate on client disconnect.
- `job["audio"]` byte-identical to the streamed PCM minus the header;
  on mid-stream failure it is truncated-but-consistent with what was heard.
- Progressive toggle ungated from `eng.streaming`; `lastUrl` untouched by the
  progressive path; no stacked `ended` listeners or download links.

## MAJOR follow-up — not in current scope, must be surfaced to the user
`engines/pocket/server.py:47,156-162` — `/v1/audio/speech/stream` is a SYNC
generator holding a `threading.Lock` for the whole generation. A client
disconnect does NOT stop it: generation runs to completion server-side while
holding the lock, stalling every subsequent request.

This fires in normal use of the feature just shipped: the user hits "Generar
voz" again mid-playback, the browser abandons the stream, and pocket stalls.
review-agent rates it MAJOR and recommends making `speech_stream`
cancellation-aware, or releasing the lock on early generator close.

Not a defect in Phases 1-2. It is a defect in code written earlier in this
project, exposed by the progressive feature.

## Minor follow-up
`speak_file()` rebuilds the whole WAV via `wave.open` even for the UI's HEAD
probe, then discards it. A `/api/speak/status/{id}` returning whether
`job["audio"]` is set would avoid it.

## Corrections to carry into the docs at closure
- CLAUDE.md / AGENTS.md / project-context.md say "the gateway does not start".
  Imprecise: `_synthesise_segment` was a NameError at call time, so uvicorn
  booted and only `GET /api/speak/stream/{id}` failed.
- Remove the "known broken state" sections entirely once Phase 3 passes.

Resume: re-read plan + this state, continue from Phase 3's report.
