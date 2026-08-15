#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$RUNTIME_DIR/.venv"

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"
unset PYTHONHOME
unset PYTHONPATH

PYTHON_REQUESTED="${PLAYMAC_ARTICLE_IMPORTER_PYTHON:-python3}"
if [[ "$PYTHON_REQUESTED" == /* ]]; then
    PYTHON_BIN="$PYTHON_REQUESTED"
else
    PYTHON_BIN="$(command -v "$PYTHON_REQUESTED" 2>/dev/null || true)"
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "服务器未找到 Python 3，请先在宝塔软件商店安装 Python 3。" >&2
    exit 1
fi

PYTHON_BIN="$("$PYTHON_BIN" -c 'import os, sys; executable = sys.executable or sys._base_executable; print(os.path.realpath(executable) if executable else "")')"
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "服务器无法确定 Python 3 的完整路径，请检查宝塔中的 Python 安装。" >&2
    exit 1
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || {
    echo "Python 版本过低，插件需要 Python 3.9 或更高版本。" >&2
    exit 1
}

"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -r "$RUNTIME_DIR/requirements.txt" >/dev/null
"$VENV_DIR/bin/python" -m playwright install chromium >/dev/null
echo "ready:$PYTHON_BIN"
