# TTS Hub

Tres motores de texto a voz **100 % locales** detrás de una sola caja de texto.
Escribes, eliges el motor, escuchas. Sin API keys, sin nube, sin telemetría.

![stack](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Los tres motores

| Motor | Modelo | Dispositivo | Español | Velocidad medida | Fuerte en |
|---|---|---|---|---|---|
| **PocketTTS** | [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) 100M | CPU | Nativo (voz `lola`) | **~3× tiempo real** | Latencia mínima, streaming |
| **Kokoro** | [Kokoro-82M](https://github.com/remsky/Kokoro-FastAPI) | CPU | `ef_dora`, `em_alex`, `em_santa` | **~3.4× tiempo real** | 68 voces, 8 idiomas |
| **Chatterbox** | [Resemble AI](https://github.com/travisvn/chatterbox-tts-api) 0.5B | GPU | 22 idiomas | depende de la GPU | Máxima calidad, clonación de voz |

> Medido en un Ryzen de 16 hilos con 4 hilos asignados al contenedor, frase de
> ~5 s de audio. Los dos motores de CPU dejan la GPU entera libre para tu LLM.

---

## Arranque

```bash
git clone https://github.com/elisaul77/tts-hub.git
cd tts-hub
cp .env.example .env        # opcional: todo tiene valores por defecto
docker compose up -d
```

Abre **<http://localhost:8600>**.

La primera vez cada motor descarga sus pesos desde Hugging Face (PocketTTS
~1.3 GB, Kokoro ~350 MB, Chatterbox ~2 GB). Hasta que terminan, la interfaz
muestra el motor en gris. Para seguir el progreso:

```bash
docker compose logs -f pocket
```

### Sin GPU

Chatterbox es el único que la necesita. O lo apagas:

```bash
docker compose stop chatterbox
```

…o lo pasas a CPU en `.env` (funciona, pero es lento):

```ini
CHATTERBOX_TAG=latest-cpu
CHATTERBOX_DEVICE=cpu
```

---

## Interfaz

- **Caja de texto** grande — `Ctrl+Enter` genera sin tocar el ratón.
- **Selector de motor** con estado en vivo: verde = listo, gris = aún no responde.
- **Selector de voz** que se repuebla al cambiar de motor y **preselecciona la
  voz española** si el motor tiene una.
- **Velocidad** (solo Kokoro, el único que la expone).
- **Streaming** para PocketTTS y Chatterbox: el audio empieza a sonar antes de
  terminar de generarse.
- Reproductor con descarga del `.wav` y el tiempo real de generación.

---

## API

El gateway habla un solo contrato, sin importar el motor que haya detrás.

```bash
# Listar motores, su estado y sus voces
curl http://localhost:8600/api/engines | jq

# Generar audio
curl -X POST http://localhost:8600/api/speak \
  -H "Content-Type: application/json" \
  -d '{"engine":"pocket","text":"Hola desde la terminal","voice":"lola"}' \
  --output salida.wav

# En streaming (PocketTTS y Chatterbox)
curl -X POST http://localhost:8600/api/speak \
  -H "Content-Type: application/json" \
  -d '{"engine":"pocket","text":"Esto suena mientras se genera","stream":true}' \
  --output salida.wav
```

Campos de `/api/speak`:

| Campo | Tipo | Por defecto | Nota |
|---|---|---|---|
| `engine` | `pocket` \| `kokoro` \| `chatterbox` | — | obligatorio |
| `text` | string | — | obligatorio |
| `voice` | string | voz por defecto del motor | ver `/api/engines` |
| `speed` | float | `1.0` | solo Kokoro |
| `stream` | bool | `false` | se ignora si el motor no lo soporta |

Cada motor sigue accesible por su cuenta si prefieres su API nativa:
PocketTTS en `:8601`, Kokoro en `:8880`, Chatterbox en `:4123`
(este último trae su propio Swagger en `/docs`).

---

## Configuración

Todo vive en `.env` (copia de `.env.example`). Lo que más se toca:

```ini
# 12 capas, ~3x tiempo real — el mejor equilibrio para conversar
POCKET_LANGUAGE=spanish
# 24 capas, mejor prosodia, ~1x tiempo real
# POCKET_LANGUAGE=spanish_24l

POCKET_VOICE=lola        # lola y rafael son las voces españolas
POCKET_THREADS=4         # subir de 4 no acelera: el cuello es el modelo
POCKET_QUANTIZE=false    # int8: más rápido, algo menos de calidad
```

Idiomas de PocketTTS: `english`, `german`, `italian`, `portuguese`, `spanish`
(12 capas) y `french_24l`, `german_24l`, `italian_24l`, `portuguese_24l`,
`spanish_24l` (24 capas).

---

## Clonación de voz

Chatterbox clona una voz a partir de 10–30 s de audio:

```bash
curl -X POST http://localhost:4123/voices \
  -F "voice_file=@mi_voz.wav" \
  -F "voice_name=mi-voz" \
  -F "language=es"
```

La voz aparece en el desplegable del hub tras recargar la página. Chatterbox
detecta el idioma a partir de los metadatos de la voz, así que la etiqueta
`language=es` importa.

PocketTTS también clona (`get_state_for_audio_prompt` acepta un `.wav`), pero
el repositorio de pesos con clonación está restringido en Hugging Face; el
contenedor cae automáticamente al repo sin clonación, que trae las voces
predefinidas ya calculadas como *embeddings* (y carga mucho más rápido).

---

## Arquitectura

```
                    ┌──────────────────────────┐
   navegador  ────► │  gateway  :8600          │
                    │  UI + normalización API  │
                    └───┬────────┬─────────┬───┘
                        │        │         │
              ┌─────────▼──┐ ┌───▼─────┐ ┌─▼────────────┐
              │ pocket     │ │ kokoro  │ │ chatterbox   │
              │ :8000 CPU  │ │ :8880   │ │ :4123 GPU    │
              │ (build)    │ │ (imagen)│ │ (imagen)     │
              └────────────┘ └─────────┘ └──────────────┘
```

`gateway/` y `engines/pocket/` se construyen desde este repo. Kokoro y
Chatterbox usan imágenes publicadas por sus autores.

Dos detalles que resuelve el gateway y que no son obvios:

1. **PocketTTS no tiene endpoint OpenAI.** `engines/pocket/server.py` envuelve
   su API de Python en `/v1/audio/speech` y añade una variante en streaming con
   cabecera RIFF de longitud abierta.
2. **Kokoro devuelve las respuestas completas con cabecera de streaming**
   (tamaños `0xFFFFFFFF`), y el navegador reporta una duración de ~89 000 s y no
   deja buscar. El gateway reescribe los tamaños del RIFF cuando ya tiene el
   archivo entero.

---

## Problemas comunes

**Un motor se queda en gris.** Sigue bajando pesos. `docker compose logs -f <servicio>`.

**Chatterbox no arranca.** Necesita el NVIDIA Container Toolkit:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```
Si eso falla, el problema está en el toolkit del host, no aquí.

**PocketTTS va lento.** Estás en `spanish_24l`. Cambia a `spanish` en `.env` y
`docker compose up -d pocket`. Subir `POCKET_THREADS` no ayuda.

**Puerto ocupado.** Cambia `GATEWAY_PORT`, `POCKET_PORT`, `KOKORO_PORT` o
`CHATTERBOX_PORT` en `.env`.

---

## Licencias

Este código es MIT. Los modelos no:

| Componente | Licencia |
|---|---|
| Pocket TTS (pesos) | CC-BY-4.0 |
| Kokoro-82M | Apache-2.0 |
| Chatterbox | MIT |

Revisa la licencia de cada **voz** por separado antes de usarla comercialmente —
en Kyutai están detalladas en [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices).
