# Build from the repo root: docker build -f api/Dockerfile .
# (api/Dockerfile.dockerignore keeps uploaded logs and data dirs out of the image)
# EXTRAS=s3,queue adds boto3 / arq for FLIGHTMD_S3_BUCKET / FLIGHTMD_REDIS_URL.
FROM python:3.11-slim-bookworm

# WeasyPrint runtime libraries only, no -dev headers
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    libffi8 \
    libjpeg62-turbo \
    libopenjp2-7 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLIGHTMD_DATA_DIR=/data

WORKDIR /app

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml README.md ./
COPY flightmd_core ./flightmd_core
COPY api ./api
ARG EXTRAS=""
RUN pip install --no-cache-dir --no-deps . \
    && if [ -n "$EXTRAS" ]; then pip install --no-cache-dir ".[$EXTRAS]"; fi

RUN useradd --system --uid 10001 --home /app flightmd \
    && mkdir -p /data \
    && chown -R flightmd /data
USER flightmd

# SQLite db, upload spool, export cache, contributed logs, topic cache
VOLUME /data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
