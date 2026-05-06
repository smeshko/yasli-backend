FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN pip install -e .

# Documentation only — Railway injects $PORT at runtime; the start command
# (uvicorn ... --port $PORT for backend-api, python -m yasli.ingest for
# backend-ingest) is supplied by the service config, not by ENTRYPOINT.
EXPOSE 8000
