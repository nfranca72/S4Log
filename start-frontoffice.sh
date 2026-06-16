#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/S4toSCP/wms-app"

if [ ! -d "$FRONTEND_DIR" ]; then
  echo "Diretoria do frontoffice nao encontrada: $FRONTEND_DIR" >&2
  exit 1
fi

cd "$FRONTEND_DIR"

if [ ! -d "node_modules" ]; then
  echo "Dependencias do frontoffice em falta. Corre 'npm install' em $FRONTEND_DIR." >&2
  exit 1
fi

exec npm run dev -- --host 0.0.0.0 --port 3000
