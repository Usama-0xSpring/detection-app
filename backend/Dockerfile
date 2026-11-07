FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# application code. The model is NOT baked in: it is downloaded at startup
# (MODEL_URL / MODEL_SHA256) into /app/models, which is a volume in compose.
COPY detector.py main.py model_store.py ./
COPY models/labels.txt /app/labels.txt
ENV LABELS_PATH=/app/labels.txt

# run as a non-root user; /app/models must be writable for the download
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/models \
    && chown -R appuser /app/models
USER appuser

EXPOSE 8000

# healthy only when the model is actually loaded
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import json,sys,urllib.request; d=json.load(urllib.request.urlopen('http://localhost:8000/health', timeout=3)); sys.exit(0 if d['model_loaded'] else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
