#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR=${UV_CACHE_DIR:-"$PWD/.uv_cache"}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-"$UV_CACHE_DIR"}

if command -v uv >/dev/null 2>&1; then
  if uv run ruff check src tests; then
    exit 0
  fi
  echo "uv run ruff failed; falling back to local venv" >&2
fi

if [[ -x ".venv/bin/ruff" ]]; then
  .venv/bin/ruff check src tests
else
  echo "ruff not available in .venv; please install dependencies (uv sync)" >&2
  exit 1
fi
