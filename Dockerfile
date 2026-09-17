# autopricer: the FastAPI app, the dashboard it serves, and the snapshot.
#
# The snapshot is baked into the image so the container is self-contained, and
# `data/raw` is also a sensible bind-mount point -- mount a freshly extracted
# snapshot over it and POST /api/reload to pick it up without a rebuild.

# Overridable only so the image can be built where Docker Hub is unreachable;
# python:3.11-slim is the base this is written against.
ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

# Stamped by the build so a running container can say which one it is.
ARG BUILD=dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so editing the app does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY autopricer ./autopricer
COPY web ./web
COPY data ./data
COPY scripts/REFRESH.md ./scripts/REFRESH.md

# Nothing here writes to disk, so the runtime user owns nothing and the
# filesystem can be mounted read-only (see compose.yaml).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin autopricer
USER 10001

ENV AUTOPRICER_BUILD=${BUILD} \
    AUTOPRICER_HOST=0.0.0.0 \
    AUTOPRICER_PORT=8765

EXPOSE 8765

# --start-period covers loading the snapshot and fitting the three surfaces,
# which the app does before it accepts a connection.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python3", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:' + os.environ.get('AUTOPRICER_PORT', '8765') + '/health', timeout=4)"]

CMD ["python3", "-m", "autopricer", "serve"]
