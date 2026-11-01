#!/usr/bin/env bash
# The repository's gate, what CI runs: lint, then the tests against a throwaway Postgres. tests/ingest spawns its own
# through testcontainers. Docker must be running.
set -euo pipefail
uv run ruff check .
port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
name="sail-gate-$$"
docker run --rm -d --name "$name" -e POSTGRES_USER=yasli -e POSTGRES_PASSWORD=yasli -e POSTGRES_DB=yasli \
  -p "127.0.0.1:$port:5432" postgres:16-alpine >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 1 60); do
  if docker exec "$name" pg_isready -U yasli -d yasli -h 127.0.0.1 >/dev/null 2>&1; then break; fi
  sleep 0.5
done
url="postgresql+psycopg://yasli:yasli@127.0.0.1:$port/yasli"
DATABASE_URL=$url YASLI_TEST_DATABASE_URL=$url uv run pytest
