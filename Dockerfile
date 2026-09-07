FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations
COPY data_catalog.yaml .
COPY streamlit_app.py .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
