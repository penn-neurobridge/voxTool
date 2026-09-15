#!/usr/bin/env bash
# Start VoxTool locally with implant-document extraction enabled.
#
#   ./run_demo.sh
#
# Sets up anything missing (Python environment, frontend build) on first run, so
# this works on a fresh clone or after a laptop restart. Ctrl-C to stop.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/web/backend"
FRONTEND="$ROOT/web/frontend"
PORT="${PORT:-5001}"
PY="${PYTHON:-/opt/homebrew/bin/python3.11}"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }

# 1. Python environment. Lives in the project, not /tmp, so it survives reboots.
if [ ! -x "$BACKEND/.venv/bin/python" ]; then
  say "Creating the Python environment (one time, ~1 min)…"
  "$PY" -m venv "$BACKEND/.venv"
  "$BACKEND/.venv/bin/pip" install -q --upgrade pip
  "$BACKEND/.venv/bin/pip" install -q -r "$BACKEND/requirements-desktop.txt"
fi

# 2. Frontend build. The backend serves these files directly.
if [ ! -f "$FRONTEND/build/index.html" ]; then
  say "Building the interface (one time, a few minutes)…"
  (cd "$FRONTEND" && npm install --silent && npm run build)
fi

# 3. Ollama. Optional: without it the document reader still works from the
#    channel map, just with no anatomical targets.
if command -v ollama >/dev/null 2>&1; then
  if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    say "Starting Ollama…"
    ollama serve >/tmp/voxtool-ollama.log 2>&1 &
    for _ in $(seq 1 30); do
      curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
      sleep 1
    done
  fi
  if curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null | grep -q "qwen2.5:7b-instruct"; then
    echo "Local model ready: qwen2.5:7b-instruct"
  else
    echo "Ollama is running but the model is missing."
    echo "  Run: ollama pull qwen2.5:7b-instruct"
  fi
else
  echo "Ollama not installed — the document reader will work without"
  echo "anatomical targets. To enable them: brew install ollama"
fi

# 4. The app. VOXTOOL_LOCAL is what unlocks the extraction endpoints; without
#    it they refuse every request, which is how the cloud build stays clear of
#    patient documents.
say "VoxTool is at http://127.0.0.1:$PORT   (Ctrl-C to stop)"
cd "$BACKEND"
exec env \
  VOXTOOL_LOCAL=1 \
  VOXTOOL_STATIC_DIR="$FRONTEND/build" \
  PORT="$PORT" \
  FLASK_DEBUG=0 \
  "$BACKEND/.venv/bin/python" app.py
