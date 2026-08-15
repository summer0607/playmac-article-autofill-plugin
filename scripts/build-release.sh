#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="$ROOT_DIR/dist"
STAGING_DIR="$(mktemp -d)"
PLUGIN_DIR="$STAGING_DIR/playmac-article-importer"

mkdir -p "$PLUGIN_DIR" "$OUTPUT_DIR"
rsync -a --delete \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='dist/' \
  --exclude='tests/' \
  --exclude='scripts/' \
  --exclude='.github/' \
  --exclude='.DS_Store' \
  "$ROOT_DIR/" "$PLUGIN_DIR/"
(cd "$STAGING_DIR" && zip -qry "$OUTPUT_DIR/playmac-article-importer.zip" playmac-article-importer)
unzip -t "$OUTPUT_DIR/playmac-article-importer.zip" >/dev/null
echo "$OUTPUT_DIR/playmac-article-importer.zip"
