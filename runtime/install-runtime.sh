#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PLAYMAC_ARTICLE_IMPORTER_PYTHON:-python3}"
VENV_DIR="$RUNTIME_DIR/.venv"

command -v "$PYTHON_BIN" >/dev/null 2>&1
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -r "$RUNTIME_DIR/requirements.txt" >/dev/null
"$VENV_DIR/bin/python" -m playwright install chromium >/dev/null
echo "ready"
