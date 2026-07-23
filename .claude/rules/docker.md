---
paths:
  - "docker-compose.yml"
  - "**/Dockerfile"
  - ".env.example"
---

# Docker Rules

## Service map

| Service | Host port | Source | Device |
|---|---|---|---|
| `gateway` | 8600 | `./gateway` | — |
| `pocket` | 8601 | `./engines/pocket` | CPU |
| `stt` | 8602 | `./engines/stt` | CPU |
| `kokoro` | 8880 | `ghcr.io/remsky/kokoro-fastapi-cpu` | CPU |
| `chatterbox` | 4123 | `travisvn/chatterbox-tts-api:gpu` | GPU |

Ports were picked to avoid the host's existing stack (Klipper 7125, Fluidd 8899,
Ollama 11434, LM Studio 1234). Do not reassign without checking `ss -ltn`.

## Rules

- Every setting exposed as `${VAR:-default}` and documented in `.env.example`.
  The stack must come up with no `.env` present.
- Only one service may reserve the GPU (`chatterbox`). The 6 GB card is shared
  with the user's LLM — CPU is the default everywhere else on purpose.
- `extra_hosts: host.docker.internal:host-gateway` on `gateway` only. It is what
  lets the container reach LM Studio/Ollama on the host.
- Model caches go in named volumes, never bind mounts, never baked into images.

## Healthchecks

Services built here define their own. For third-party images, **verify the
baked-in healthcheck matches the port we run on** — the Chatterbox image ships
one hardcoded to `:5123` while the service listens on `:4123`, so it reports
unhealthy forever unless overridden in compose.

Give model-loading services a long `start_period` (180–300 s). They download
weights on first boot.

## Dockerfiles

- Base `python:3.12-slim`. Install `curl` for healthchecks.
- Install CPU-only torch explicitly from the PyTorch CPU index — it saves ~2 GB
  and PocketTTS sees no GPU speedup anyway:
  `pip install torch --index-url https://download.pytorch.org/whl/cpu`
- Copy `requirements.txt` and install *before* copying source, so code edits
  don't invalidate the dependency layer.
- `ENV HF_HOME=/cache` so Hugging Face downloads land in the mounted volume.

## After editing

```bash
docker compose config --quiet          # syntax
docker compose up -d --build <service> # rebuild only what changed
docker compose ps                      # all healthy?
```
