FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GARDEN_APP_DIR=/app \
    GARDEN_DATA=/data

WORKDIR /app

# The venv lives at /app/venv so deploy/backup.sh works unchanged inside the container.
COPY requirements.txt .
RUN python -m venv venv \
 && venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY deploy ./deploy

RUN useradd --system --uid 1000 --home-dir /app garden \
 && mkdir -p /data \
 && chown garden:garden /data
USER garden
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# Open SSE streams never close on their own, so cap how long shutdown waits.
CMD ["venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "3"]
