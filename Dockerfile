FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

LABEL org.opencontainers.image.title="TiffGetter" \
      org.opencontainers.image.description="Multi-source satellite imagery downloader (CLI)" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/eryieryiya/TiffGetter"

WORKDIR /app

COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY main.py config.py satellite_processor.py coordinate_loader.py ./
COPY core ./core
COPY providers ./providers
COPY utils ./utils
COPY LICENSE ./

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/output \
    && chown -R app:app /app

USER app
ENV HOME=/home/app

VOLUME ["/app/data/output"]
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
