# TTS Hub — Project Conventions

Always applies. Read before touching anything in this repo.

## Language split

| Where | Language |
|---|---|
| Code, identifiers, comments, docstrings | English |
| Commit messages | English |
| README, UI strings, error text shown to the user | Spanish |

This split is deliberate: the code is meant to be readable by anyone, the
product is for a Spanish-speaking user.

## Editing discipline

`gateway/main.py` is a god node (~737 lines). It is a flat module by design —
five small files importing each other would be worse for a service this size.
The tradeoff is that edits must be **surgical**:

- Edit the named function only. Never rewrite a whole section.
- Never reorder routes or move helpers between sections.
- When adding a route, put it in the matching `# ---` section block.

Same for `docker-compose.yml`: change only the named key. Never replace a
service block wholesale.

## Docker rules

- Everything runs in containers. Never `pip install` a model runtime on the host.
- Services built here: `gateway`, `pocket`, `stt`. Everything else is a pinned
  third-party image.
- After changing a `server.py` or `main.py`, rebuild that service only:
  `docker compose up -d --build <service>`.
- Model weights live in named volumes (`pocket-cache`, `stt-cache`,
  `chatterbox-models`). Never bake weights into an image.

## Verification before claiming done

A change is not done until it has been exercised against the running stack:

```bash
curl -s localhost:8600/api/engines | jq          # all engines online?
curl -s localhost:8600/api/services | jq         # stt + llm reachable?
docker compose ps                                 # all healthy?
docker compose logs --tail=30 <service>           # no tracebacks?
```

For audio changes, verify the bytes, not just the status code: check duration,
sample rate and RMS. A 200 response with silence is the most common failure.

## Commits

Conventional commits. The body explains *why*, and calls out any non-obvious
behaviour discovered along the way — this repo's history is where the
third-party API quirks are recorded.

```
fix: detect engine capabilities instead of hardcoding them

The chatterbox :gpu image has neither /voices nor a streaming endpoint, so
the hardcoded streaming=True made the UI offer a button that 404s.
```

## Do not

- Do not add a dependency to solve something the standard library covers
  (`wave`, `struct`, `re` already handle all WAV and text work here).
- Do not introduce a frontend build step. The UI is one self-contained HTML file.
- Do not hardcode sample rates, voice names, or engine capabilities.
