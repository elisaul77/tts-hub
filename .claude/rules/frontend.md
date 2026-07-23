---
paths:
  - "gateway/static/*.html"
---

# UI Rules — single-file vanilla JS

`gateway/static/index.html` is the entire frontend: markup, CSS and JS in one
file, served directly by FastAPI. This is intentional.

## Hard constraints

- **No build step. No framework. No CDN.** The container serves this file as-is
  and has no network egress guarantee.
- Everything inline: `<style>` in head, `<script>` at the end of body.
- Plain DOM APIs. `const $ = (id) => document.getElementById(id);` is the only
  helper.

## Styling

- CSS custom properties on `:root`, with a `@media (prefers-color-scheme: light)`
  block overriding them. Both themes must stay legible — check text on panels,
  not just the background.
- Never hardcode a colour outside the `:root` blocks.
- Layout with flex/grid and relative units. The page must not scroll sideways.

## State

- Module-scope `let` for UI state (`engines`, `selected`, `history`, `recording`).
- Conversation history lives here and is posted per turn. The server keeps none.
- Always `URL.revokeObjectURL(lastUrl)` before assigning a new blob URL —
  audio blobs are megabytes and leak fast.

## Talking to the API

- Every call goes to the gateway's `/api/*`, never to an engine port directly.
  The browser cannot reach engine containers by service name.
- Check `res.ok` and surface the body text: `throw new Error((await res.text()).slice(0, 300))`.
- Render capability from `/api/engines`, never from a hardcoded list. If an
  engine reports `streaming: false`, disable the control rather than hiding it.

## User-facing text

Spanish. Concrete over generic: "El LLM no responde. En LM Studio activa
'Serve on local network'." beats "Error de conexión".

## Audio playback

- Complete audio → fetch as blob, `URL.createObjectURL`, assign to `<audio>.src`.
- Progressive audio → assign the streaming URL **directly** to `<audio>.src`.
  Do not `await res.blob()` on a stream; that defeats the entire purpose and is
  the bug this UI currently has.
