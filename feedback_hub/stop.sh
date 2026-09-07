#!/bin/sh
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/server.py" ] && [ -f "$HERE/__main__.py" ]; then
  PKG="$HERE"
else
  PKG="$HERE/feedback_hub"
fi
PIDF="$PKG/data/hub.pid"
if [ ! -f "$PIDF" ]; then
  echo "not running"
  exit 0
fi
pid="$(cat "$PIDF")"
if [ -n "$pid" ]; then
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill -9 "$pid" 2>/dev/null || true
fi
rm -f "$PIDF"
echo "stopped"
