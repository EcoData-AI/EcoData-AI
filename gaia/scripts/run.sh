#!/usr/bin/env bash
#
# Run GAIA without the desktop shell.
#
# Starts the backend, which also serves the built interface, then opens it in
# your default browser. Useful before you have built the desktop app, and for
# development. Ctrl-C stops everything.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/backend/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  echo "GAIA is not installed yet. Run ./scripts/install.sh first." >&2
  exit 1
fi

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "The interface has not been built. Run ./scripts/install.sh first." >&2
  exit 1
fi

PORT="${GAIA_PORT:-8756}"
URL="http://127.0.0.1:${PORT}"

cleanup() { [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

"$PYTHON" -m gaia --port "$PORT" &
BACKEND_PID=$!

printf 'Starting GAIA'
for _ in $(seq 1 60); do
  if curl -sf "$URL/api/health" >/dev/null 2>&1; then
    printf ' ready\n\n  %s\n\n' "$URL"
    case "$(uname -s)" in
      Darwin) open "$URL" ;;
      Linux)  command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || true ;;
    esac
    wait "$BACKEND_PID"
    exit 0
  fi
  printf '.'
  sleep 0.5
done

echo
echo "The backend did not start. Check the log in your GAIA data directory." >&2
exit 1
