# Reflex needs Node.js at build time (compiles the React frontend) and
# at runtime (serves it) — the plain python:3.12-slim base the rest of
# this project uses has no Node, so this is a separate Dockerfile, not
# an addition to the root one (ADR-012).
FROM python:3.12-slim

# unzip is required by Reflex's own bun installer, not obviously so from
# its docs — caught only by actually running the built image
# (`SystemPackageMissingError: System package 'unzip' is missing`), not
# assumed from a Node-only Dockerfile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The root package (app/*) is what frontend/state.py imports directly,
# in-process (ADR-012: no separate API service, no HTTP hop).
COPY pyproject.toml .
COPY app ./app
RUN pip install --no-cache-dir -e .

COPY frontend ./frontend
WORKDIR /app/frontend

EXPOSE 8000
CMD ["reflex", "run", "--env", "prod", "--single-port", "--backend-port", "8000"]
