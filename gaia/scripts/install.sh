#!/usr/bin/env bash
#
# GAIA installer for macOS and Linux.
#
#   ./scripts/install.sh              install everything
#   ./scripts/install.sh --build      also produce a desktop installer
#
# Creates a virtualenv for the backend and builds the frontend. Nothing is
# installed system-wide and no user data is written by this script.

set -euo pipefail

BUILD_DESKTOP=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD_DESKTOP=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- checks

say "Checking prerequisites"

PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
    major="${version%%.*}"; minor="${version##*.}"
    if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then PYTHON="$candidate"; break; fi
  fi
done
[ -n "$PYTHON" ] || fail "Python 3.10+ is required. Install it, then run this script again."
ok "Python $("$PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))') ($PYTHON)"

command -v node >/dev/null 2>&1 || fail "Node.js 18+ is required (https://nodejs.org)."
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || fail "Node.js 18+ is required; found $(node -v)."
ok "Node $(node -v)"

if [ "$BUILD_DESKTOP" -eq 1 ]; then
  command -v cargo >/dev/null 2>&1 || fail "Rust is required to build the desktop app (https://rustup.rs)."
  ok "Rust $(rustc --version | cut -d' ' -f2)"
  if [ "$(uname -s)" = "Linux" ] && ! pkg-config --exists webkit2gtk-4.1 2>/dev/null; then
    echo
    echo "  Missing Tauri system libraries. On Debian/Ubuntu:"
    echo "    sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev \\"
    echo "         libayatana-appindicator3-dev librsvg2-dev patchelf build-essential curl wget file libssl-dev"
    fail "Install the packages above, then re-run with --build."
  fi
fi

# --------------------------------------------------------------- backend

say "Installing the backend"
cd "$ROOT/backend"
[ -d .venv ] || "$PYTHON" -m venv .venv
ok "virtualenv at backend/.venv"
./.venv/bin/python -m pip install --quiet --upgrade pip setuptools wheel
./.venv/bin/python -m pip install --quiet -e .
ok "backend dependencies installed"

[ -f .env ] || { [ -f .env.example ] && cp .env.example .env && ok "created backend/.env from the example"; }

# -------------------------------------------------------------- frontend

say "Building the interface"
cd "$ROOT/frontend"
npm install --no-audit --no-fund --silent
npm run build --silent
ok "frontend built to frontend/dist"

# --------------------------------------------------------------- desktop

if [ "$BUILD_DESKTOP" -eq 1 ]; then
  say "Building the desktop application (this takes several minutes the first time)"
  cd "$ROOT"
  npm install --no-audit --no-fund --silent
  npx tauri build
  ok "installer written to src-tauri/target/release/bundle/"
fi

# ----------------------------------------------------------------- done

say "GAIA is installed"
cat <<EOF
  Start it with:
      ./scripts/run.sh

  Or build a double-clickable desktop app:
      ./scripts/install.sh --build

  Your data will live outside this folder, in your platform's application
  data directory. GAIA will show you the exact path in Settings → Data.
EOF
