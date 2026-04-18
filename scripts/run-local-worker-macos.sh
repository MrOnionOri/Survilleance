#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT/worker"
PYTHON_EXE="$WORKER_DIR/.venv/bin/python"

if [ ! -x "$PYTHON_EXE" ]; then
  echo "No existe el venv del worker. Creandolo ahora..."
  "$ROOT/scripts/setup-local-worker-macos.sh"
fi

export BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
export WORKER_EMAIL="${WORKER_EMAIL:-admin@streamwatch.example.com}"
export WORKER_PASSWORD="${WORKER_PASSWORD:-admin123}"
export STREAMWATCH_DATA_DIR="${STREAMWATCH_DATA_DIR:-$ROOT}"
export WORKER_SOURCE_SCOPE="${WORKER_SOURCE_SCOPE:-local}"

cd "$WORKER_DIR"
"$PYTHON_EXE" -m app.main
