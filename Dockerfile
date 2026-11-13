# Reproducible runtime for `pvt` (docs/06 section 3). ecCodes comes from the eccodeslib wheel.
FROM python:3.12-slim-bookworm
ARG PVT_INGEST_VERSION=unknown
ENV PVT_INGEST_VERSION=${PVT_INGEST_VERSION} \
    PVT_DATA_ROOT=/data \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"
RUN pip install --no-cache-dir "uv==0.11.32" && useradd --create-home --uid 10001 pvt
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev && chown -R pvt /app
COPY config ./config
USER pvt
VOLUME ["/data"]
ENTRYPOINT ["pvt"]
CMD ["--help"]
