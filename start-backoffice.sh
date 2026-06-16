#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/S4toSCP/wms-scpapp/backend"

if [ ! -d "$BACKEND_DIR" ]; then
  echo "Diretoria do backoffice nao encontrada: $BACKEND_DIR" >&2
  exit 1
fi

cd "$BACKEND_DIR"

if [ -x ".venv311/bin/python" ]; then
  PYTHON_BIN=".venv311/bin/python"
elif [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
else
  echo "Nao encontrei um ambiente virtual em $BACKEND_DIR/.venv311 ou .venv" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
