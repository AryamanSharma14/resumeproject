# Local-only image. Digest-pinned bases and multi-arch rehearsal are release gates.
FROM node:26.9.0-bookworm-slim AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13.5-slim-bookworm AS builder
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=0
RUN python -m pip install --no-cache-dir uv==0.11.7
WORKDIR /build
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ src/
COPY scripts/build_release.py scripts/build_release.py
COPY web/package-lock.json web/package-lock.json
COPY --from=web /build/web/dist web/dist
RUN python scripts/build_release.py --output /artifacts
# Sync locked production dependencies, then replace editable root with the wheel.
RUN uv sync --locked --no-dev --no-install-project --no-editable \
    && uv pip install --python /build/.venv/bin/python --no-deps /artifacts/*.whl

FROM python:3.13.5-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RELAY_DATA_DIR=/var/lib/relay
RUN groupadd --gid 10001 relay \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /var/lib/relay relay \
    && mkdir /var/lib/relay \
    && chown 10001:10001 /var/lib/relay \
    && chmod 700 /var/lib/relay
# Keep the venv's original absolute prefix for its console-script shebangs.
COPY --from=builder /build/.venv /build/.venv
ENV PATH=/build/.venv/bin:$PATH
USER 10001:10001
WORKDIR /var/lib/relay
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"]
ENTRYPOINT ["relay"]
CMD ["serve", "--port", "8000"]
