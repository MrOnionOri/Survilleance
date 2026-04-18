#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT/worker"
PYTHON_EXE="$WORKER_DIR/.venv/bin/python"
MAX_INDEX="${1:-5}"

if [ ! -x "$PYTHON_EXE" ]; then
  echo "No existe el venv del worker. Creandolo ahora..."
  "$ROOT/scripts/setup-local-worker-macos.sh"
fi

cd "$WORKER_DIR"
CAMERA_PROBE_OUTPUT_DIR="$WORKER_DIR/camera_probe" "$PYTHON_EXE" -m app.probe_cameras --max-index "$MAX_INDEX"
