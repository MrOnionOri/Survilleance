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
export WORKER_PRINT_LOCAL_CAMERAS="${WORKER_PRINT_LOCAL_CAMERAS:-true}"
export WORKER_CAMERA_PROBE_MAX_INDEX="${WORKER_CAMERA_PROBE_MAX_INDEX:-8}"
export EVENT_COOLDOWN_SECONDS="${EVENT_COOLDOWN_SECONDS:-10}"
export VIDEO_STREAM_MAX_FPS="${VIDEO_STREAM_MAX_FPS:-15}"

if [ -z "${IMAGEIO_FFMPEG_EXE:-}" ] && command -v ffmpeg >/dev/null 2>&1; then
  export IMAGEIO_FFMPEG_EXE="$(command -v ffmpeg)"
fi

if [ -z "${IMAGEIO_FFMPEG_EXE:-}" ]; then
  echo "Aviso: no encontre ffmpeg. El vivo y detecciones funcionaran, pero la grabacion MP4 se desactivara."
  echo "Instalalo con: brew install ffmpeg"
fi

cd "$WORKER_DIR"
"$PYTHON_EXE" -m app.main
