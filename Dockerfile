FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTCLM_PORT=5025 \
    FASTCLM_DATA_DIR=/data \
    FASTCLM_DB=/data/fastclm.sqlite \
    FASTCLM_UPLOAD_DIR=/data/uploads

WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md LICENSE ./
COPY fastclm ./fastclm
COPY migrations ./migrations
COPY static ./static
COPY web_app.py seed.py ./
RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 fastclm \
    && mkdir -p /data/uploads \
    && chown -R fastclm:fastclm /data /app
USER fastclm
EXPOSE 5025
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5025/healthz', timeout=3)"
CMD ["python", "web_app.py"]
