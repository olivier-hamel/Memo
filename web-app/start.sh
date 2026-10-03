#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

# Private local settings are opt-in and never included in the Docker image.
if [[ -f .env.memo-local ]]; then
  set -a
  source .env.memo-local
  set +a
fi

if ! command -v python3 >/dev/null || ! command -v npm >/dev/null; then
  echo "Installe Python 3.10+ et Node.js 22.12+ (avec npm) pour lancer Mémo."
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, httpx, pwdlib, pymongo, curl_cffi' 2>/dev/null; then
  .venv/bin/python -m pip install -r backend/requirements.lock.txt
fi
if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && npm ci)
fi

if [[ "${1:-}" == "--dev" ]]; then
  exec .venv/bin/python dev.py
elif [[ -n "${1:-}" ]]; then
  echo "Usage : ./start.sh [--dev]"
  exit 1
fi

(cd frontend && npm run build)
echo "Mémo est disponible sur http://localhost:8000 — Ctrl+C pour arrêter."
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
