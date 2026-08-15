FROM python:3.12-slim-bookworm

ARG PLAYMAC_RUNTIME_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PLAYMAC_RUNTIME_DATA=/data \
    PLAYMAC_RUNTIME_PORT=8080 \
    PLAYMAC_RUNTIME_VERSION=${PLAYMAC_RUNTIME_VERSION}

WORKDIR /app

COPY runtime/requirements.txt /app/runtime/requirements.txt
RUN pip install --no-cache-dir -r /app/runtime/requirements.txt \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 playmac \
    && mkdir -p /data \
    && chown -R playmac:playmac /data /app /ms-playwright

COPY runtime/playmac_article_worker.py /app/runtime/playmac_article_worker.py
COPY service/runtime_server.py /app/service/runtime_server.py

USER playmac

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD ["python", "-c", "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)); raise SystemExit(0 if data.get('success') else 1)"]

CMD ["python", "/app/service/runtime_server.py"]
