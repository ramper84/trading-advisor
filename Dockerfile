FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY data_catalog.yaml .

# No default CMD tied to a service that no longer exists (ADR-012 drops
# the standalone `api` service) — `migrate` and `refresh_worker`
# (docker-compose.yml) both override `command:` explicitly. `routers/*`
# stays a reserved capability, not something this image runs by default.
CMD ["python", "-m", "app.ingest.refresh_worker"]
