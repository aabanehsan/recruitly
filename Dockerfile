# Recruitly in a container: `docker compose up`, then open http://localhost:8000
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RECRUITLY_DATA_DIR=/data

WORKDIR /app

# install dependencies first so code changes don't re-download them
COPY pyproject.toml README.md LICENSE ./
COPY recruitly ./recruitly
RUN pip install ".[postgres]" \
    && useradd --create-home --uid 1000 recruitly \
    && mkdir -p /data && chown recruitly:recruitly /data

COPY docker/entrypoint.sh /usr/local/bin/recruitly-entrypoint
RUN chmod 755 /usr/local/bin/recruitly-entrypoint

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

ENTRYPOINT ["recruitly-entrypoint"]
CMD ["recruitly", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
