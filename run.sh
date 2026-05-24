#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ ! -d .venv ] && uv sync
exec uv run python main.py
