# TTS Hub

Tres motores de texto a voz **100 % locales** detrás de una sola caja de texto.
Escribes, eliges el motor, escuchas. Sin API keys, sin nube, sin telemetría.

Y una segunda pestaña para **hablar** con tu LLM local: micrófono → Whisper →
LM Studio (u Ollama) → voz, sin que ningún audio salga de la máquina.

![stack](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green)

---

## Los tres motores

| Motor | Modelo | Dispositivo | Español | Velocidad medida | Fuerte en |
|---|---|---|---|---|---|
| **PocketTTS** | [Kyutai Pocket TTS](https://github.com/kyutai-labs/pocket-tts) 100M | CPU | Nativo (voces `lola`, `rafael`) | **3.0× tiempo real** | Latencia mínima, streaming |
| **Kokoro** | [Kokoro-82M](https://github.com/remsky/Kokoro-FastAPI) | CPU | `ef_dora`, `em_alex`, `em_santa` | **4.1× tiempo real** | 68 voces, 8 idiomas |
| **Chatterbox** | [Resemble AI](https://github.com/travisvn/chatterbox-tts-api) 0.5B | GPU | 22 idiomas | **1.3× tiempo real** | Máxima calidad, clonación de voz |

> Medido en una misma frase de ~4 s: CPU de 16 hilos (4 asignados al contenedor
> de PocketTTS) y GPU RTX 3050 de 6 GB para Chatterbox. Los dos motores de CPU
> dejan la GPU entera libre para tu LLM.

Más un cuarto servicio para la escucha:

| Servicio | Modelo | Dispositivo | Velocidad medida |
|---|---|---|---|
| **STT** | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `small` int8 | CPU | 2.3× tiempo real |

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
- **Detección de streaming nativo**: el gateway mira el `openapi.json` de cada
  motor para saber si tiene streaming propio, así acierta aunque cambies de
  versión de imagen (hoy: PocketTTS sí; Kokoro y el Chatterbox `gpu` actual,
  no). Eso decide, de forma invisible para ti, si la reproducción progresiva
  (ver abajo) retransmite ese streaming trozo a trozo o cae a una petición
  por segmento — ya no es algo que actives con una casilla.
- Reproductor con descarga del `.wav`. En modo normal se ve el tiempo real de
  generación al terminar; en progresiva, el enlace de descarga aparece
  cuando termina de sonar el audio (detalle abajo).

### Reproducción progresiva

La casilla **«Progresiva»** parte el texto en frases y sintetiza segmento a
segmento, de modo que el audio empieza a sonar en cuanto el primer trozo está
listo, en vez de esperar a que se genere el texto completo. Está marcada por
defecto y funciona con cualquier motor en línea: el que tiene streaming
nativo (hoy, PocketTTS) entrega cada trozo de audio según se va generando; el
resto recibe una petición por segmento, que sigue siendo mucho más rápida que
esperar el texto entero de una vez.

Medido con un párrafo en español de 851 caracteres (6 segmentos):

| Motor | Modo | Primer audio | Duración total |
|---|---|---|---|
| PocketTTS | normal | 18,6 s | 48,2 s |
| PocketTTS | progresiva | 0,24 s | 53,6 s |
| Kokoro | normal | 17,0 s | 49,0 s |
| Kokoro | progresiva | 1,9 s | 49,8 s |

PocketTTS empieza a sonar 77 veces antes; Kokoro, 9 veces antes.

El enlace de descarga aparece cuando termina la reproducción: mientras el
audio suena, el servidor todavía está ensamblando el archivo completo.

---

## Conversar con tu LLM

La pestaña **Conversar** cierra el bucle: pulsas el micrófono, hablas, vuelves a
pulsar y el asistente te contesta en voz alta. El historial se mantiene en el
navegador (últimos 12 mensajes), así que el gateway no guarda nada.

```
micrófono ──► Whisper ──► LM Studio ──► motor TTS elegido ──► altavoz
   (navegador)   (CPU)      (tu GPU)        (CPU o GPU)
```

### Conectar LM Studio

En LM Studio: pestaña **Developer** → arranca el servidor → activa
**«Serve on local network»**. Sin eso escucha solo en `127.0.0.1` y el
contenedor no lo alcanza. Después:

```ini
LLM_URL=http://host.docker.internal:1234/v1
LLM_MODEL=            # vacío = usa el modelo que tengas cargado
```

### Conectar Ollama

```ini
LLM_URL=http://host.docker.internal:11434/v1
LLM_MODEL=qwen3.5-9b-q4_k_m:latest
```

Ollama también escucha solo en loopback por defecto; arráncalo con
`OLLAMA_HOST=0.0.0.0`.

La pestaña muestra el estado de Whisper y del LLM en vivo, y desactiva el
micrófono si falta alguno. Comprobación rápida desde la terminal:

```bash
curl http://localhost:8600/api/services | jq
```

> El primer turno puede tardar bastante mientras el LLM carga el modelo en
> memoria. En un turno ya caliente, con Whisper `small` en CPU y un modelo de
> 4B, la vuelta completa desde que sueltas el micrófono ronda los 4 segundos.

### Ajustar el asistente

`SYSTEM_PROMPT` en `.env`. El de fábrica le pide respuestas breves, sin markdown
ni emojis y con las cifras escritas en palabras — todo eso suena fatal leído en
voz alta.

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

# En streaming (hoy solo PocketTTS tiene streaming nativo)
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
| `stream` | bool | `false` | se ignora si el motor no lo soporta (hoy solo PocketTTS) |

### Endpoints de la reproducción progresiva

Los cuatro endpoints que usa la casilla «Progresiva» de la interfaz también
están disponibles sueltos:

```bash
# Previsualizar cómo se partiría el texto, sin sintetizar nada — útil para
# ajustar SEGMENT_MIN_CHARS / SEGMENT_MAX_CHARS
curl -X POST http://localhost:8600/api/segment \
  -H "Content-Type: application/json" \
  -d '{"text":"Primera frase. Segunda frase."}'
# → {"count":2,"segments":["Primera frase.","Segunda frase."]}

# Registrar un trabajo (mismo cuerpo que /api/speak)
curl -X POST http://localhost:8600/api/speak/prepare \
  -H "Content-Type: application/json" \
  -d '{"engine":"pocket","text":"Hola desde la terminal","voice":"lola"}'
# → {"id":"...","count":1,"segments":["Hola desde la terminal"]}

# Reproducirlo mientras se va generando (.wav troceado)
curl http://localhost:8600/api/speak/stream/<id> --output salida.wav

# El archivo ya ensamblado, para descargar
curl http://localhost:8600/api/speak/file/<id> --output salida.wav
```

`/api/speak/stream/{id}` escribe la cabecera RIFF con tamaños en blanco
(`0xFFFFFFFF`) a propósito, porque la duración no se conoce hasta que termina
de generarse — algunos reproductores no mostrarán duración ni dejarán buscar
dentro del audio mientras lo consumes así. `/api/speak/file/{id}` sí trae los
tamaños correctos, pero responde 409 si el streaming todavía no ha terminado.
Los trabajos caducan a los 30 minutos o en cuanto existen 20 más nuevos que
ellos.

Y para el bucle conversacional:

```bash
# Solo transcribir
curl -X POST http://localhost:8600/api/transcribe -F "file=@audio.wav"

# Solo el LLM
curl -X POST http://localhost:8600/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hola"}]}'

# Un turno entero: audio -> transcripción + respuesta
curl -X POST http://localhost:8600/api/converse \
  -F "file=@pregunta.wav" -F 'history=[]'
```

`/api/converse` devuelve `{"user_text": ..., "reply_text": ...}` y **no**
sintetiza: el cliente manda ese texto a `/api/speak` con el motor y la voz que
tenga elegidos, lo que permite mostrar la respuesta escrita mientras el audio
todavía se está generando.

Cada motor sigue accesible por su cuenta si prefieres su API nativa:
PocketTTS en `:8601`, Whisper en `:8602`, Kokoro en `:8880`, Chatterbox en
`:4123` (este último trae su propio Swagger en `/docs`).

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

Chatterbox clona una voz a partir de 10–30 s de audio. En cualquier versión
funciona la clonación de un solo uso, subiendo la muestra con el texto:

```bash
curl -X POST http://localhost:4123/v1/audio/speech/upload \
  -F "input=Hola, esta es mi voz clonada." \
  -F "voice_file=@mi_voz.wav" \
  --output clonada.wav
```

Las versiones recientes añaden además una biblioteca de voces con nombre:

```bash
curl -X POST http://localhost:4123/voices \
  -F "voice_file=@mi_voz.wav" -F "voice_name=mi-voz" -F "language=es"
```

Si tu imagen la trae, la voz aparece en el desplegable del hub al recargar; si
no, el endpoint responde 404 y el hub simplemente ofrece la voz `default`.
Comprueba qué soporta tu imagen con `curl http://localhost:4123/openapi.json`.

PocketTTS también clona (`get_state_for_audio_prompt` acepta un `.wav`), pero
el repositorio de pesos con clonación está restringido en Hugging Face; el
contenedor cae automáticamente al repo sin clonación, que trae las voces
predefinidas ya calculadas como *embeddings* (y carga mucho más rápido).

---

## Arquitectura

```
                        ┌──────────────────────────┐
       navegador  ────► │  gateway  :8600          │ ────► LM Studio / Ollama
      (UI + micro)      │  UI + normalización API  │        (en el host)
                        └──┬─────┬──────┬───────┬──┘
                           │     │      │       │
                 ┌─────────▼─┐ ┌─▼────┐ ┌▼─────────────┐ ┌▼──────────┐
                 │ pocket    │ │kokoro│ │ chatterbox   │ │ stt       │
                 │ :8000 CPU │ │:8880 │ │ :4123 GPU    │ │ :8000 CPU │
                 │ (build)   │ │(img) │ │ (img)        │ │ (build)   │
                 └───────────┘ └──────┘ └──────────────┘ └───────────┘
```

`gateway/`, `engines/pocket/` y `engines/stt/` se construyen desde este repo.
Kokoro y Chatterbox usan imágenes publicadas por sus autores.

Dos detalles que resuelve el gateway y que no son obvios:

1. **PocketTTS no tiene endpoint OpenAI.** `engines/pocket/server.py` envuelve
   su API de Python en `/v1/audio/speech` y añade una variante en streaming con
   cabecera RIFF de longitud abierta.
2. **Kokoro devuelve las respuestas completas con cabecera de streaming**
   (tamaños `0xFFFFFFFF`), y el navegador reporta una duración de ~89 000 s y no
   deja buscar. El gateway reescribe los tamaños del RIFF cuando ya tiene el
   archivo entero.
3. **Las capacidades se detectan, no se dan por supuestas.** Antes de pedir
   streaming, el gateway mira el `openapi.json` del motor; si no existe la ruta,
   cae a la petición normal en vez de devolver un 404.

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

**Puerto ocupado.** Cambia `GATEWAY_PORT`, `POCKET_PORT`, `STT_PORT`,
`KOKORO_PORT` o `CHATTERBOX_PORT` en `.env`.

**El LLM sale «sin conexión».** Casi siempre es que el servidor escucha solo en
`127.0.0.1`: activa «Serve on local network» en LM Studio o arranca Ollama con
`OLLAMA_HOST=0.0.0.0`. Verifica con
`docker compose exec gateway curl -s $LLM_URL/models`.

**El micrófono no aparece.** El navegador solo da acceso en contexto seguro. En
`http://localhost:8600` funciona; si abres el hub desde otra máquina por su IP
necesitarás HTTPS o marcar el origen como fiable en el navegador.

**Whisper transcribe mal.** Sube de `small` a `medium` en `STT_MODEL`, o fija
`STT_LANGUAGE=es` si lo tenías en automático — con frases cortas la detección
automática de idioma falla más de lo que parece.

---

## Licencias

Este código es MIT. Los modelos no:

| Componente | Licencia |
|---|---|
| Pocket TTS (pesos) | CC-BY-4.0 |
| Kokoro-82M | Apache-2.0 |
| Chatterbox | MIT |
| faster-whisper / Whisper | MIT |

Revisa la licencia de cada **voz** por separado antes de usarla comercialmente —
en Kyutai están detalladas en [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices).
