#!/bin/sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/server.py" ] && [ -f "$HERE/__main__.py" ]; then
  ROOT="$(cd "$HERE/.." && pwd)"
  PKG="$HERE"
else
  ROOT="$HERE"
  PKG="$HERE/feedback_hub"
fi
cd "$ROOT"
mkdir -p "$PKG/data"
PIDF="$PKG/data/hub.pid"
LOG="$PKG/data/hub.log"
if [ -f "$PIDF" ]; then
  old="$(cat "$PIDF" 2>/dev/null || true)"
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    echo "already running pid=$old"
    exit 0
  fi
fi
PY="${PYTHON:-python3}"
nohup "$PY" -m feedback_hub >>"$LOG" 2>&1 &
echo $! >"$PIDF"
echo "started pid=$(cat "$PIDF")"
echo "ingest :18788  ui :18789  log=$LOG"
