#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="$ROOT/worker"
VENV_DIR="$WORKER_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "No encontre $PYTHON_BIN. Instala Python 3 y vuelve a intentar."
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "El worker necesita Python 3.10 o superior. Puedes usar PYTHON_BIN=/ruta/python3.12 ./scripts/setup-local-worker-macos.sh"
  exit 1
}

if [ ! -d "$VENV_DIR" ]; then
  echo "Creando entorno virtual del worker..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "Instalando dependencias del worker para macOS..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$WORKER_DIR/requirements-macos.txt"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Aviso: no encontre ffmpeg. Para grabar chunks MP4 instala ffmpeg con: brew install ffmpeg"
fi

echo "Worker local para macOS listo."
echo "Para probar camaras: ./scripts/probe-local-cameras-macos.sh"
echo "Para ejecutarlo: ./scripts/run-local-worker-macos.sh"
