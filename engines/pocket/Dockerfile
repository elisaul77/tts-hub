FROM python:3.12-slim

# ffmpeg + libsndfile let soundfile decode the .mp3/.wav voice prompts that
# Pocket TTS pulls from Hugging Face.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch: Pocket TTS sees no speedup on GPU and this keeps the image
# roughly 2 GB smaller.
RUN pip install --no-cache-dir torch>=2.5.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV HF_HOME=/cache \
    OMP_NUM_THREADS=4

EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
