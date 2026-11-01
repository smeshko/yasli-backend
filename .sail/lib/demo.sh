#!/usr/bin/env bash
# Starts a throwaway Postgres, seeds it from the committed data and serves the API, each on a free port, runs one command
# with $API_URL and $DATABASE_URL set, and stops both whatever happens.
# Usage: .sail/lib/demo.sh <command> [args…]
set -euo pipefail
[ $# -gt 0 ] || { echo 'usage: demo.sh <command> [args…]' >&2; exit 2; }
free_port() { python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
db=$(free_port)
web=$(free_port)
name="sail-demo-$$"
logs=$(mktemp -d)
api_pid=
stop() {
  [ -z "$api_pid" ] || kill -TERM -- "-$api_pid" 2>/dev/null || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  rm -rf "$logs"
}
trap stop EXIT
docker run --rm -d --name "$name" -e POSTGRES_USER=yasli -e POSTGRES_PASSWORD=yasli -e POSTGRES_DB=yasli \
  -p "127.0.0.1:$db:5432" postgres:16-alpine >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$name" pg_isready -U yasli -d yasli -h 127.0.0.1 >/dev/null 2>&1; then break; fi
  sleep 0.5
done
export DATABASE_URL="postgresql+psycopg://yasli:yasli@127.0.0.1:$db/yasli"
export API_URL="http://127.0.0.1:$web"
uv run python -m yasli.seed >"$logs/seed.log" 2>&1 || { echo 'demo: the seed failed' >&2; cat "$logs/seed.log" >&2; exit 2; }
set -m
uv run uvicorn yasli.main:app --host 127.0.0.1 --port "$web" >"$logs/api.log" 2>&1 &
api_pid=$!
set +m
for _ in $(seq 1 60); do
  if curl -fs -o /dev/null "$API_URL/api/health"; then break; fi
  sleep 0.5
done
curl -fs -o /dev/null "$API_URL/api/health" || { echo 'demo: the API did not start' >&2; cat "$logs/api.log" >&2; exit 2; }
"$@"
