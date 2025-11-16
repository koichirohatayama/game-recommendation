#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR=${UV_CACHE_DIR:-"$PWD/.uv_cache"}
export XDG_CACHE_HOME=${XDG_CACHE_HOME:-"$UV_CACHE_DIR"}

FIX_MODE=false
for arg in "$@"; do
  if [[ "$arg" == "--fix" ]]; then
    FIX_MODE=true
  else
    echo "Unknown argument: $arg" >&2
    exit 1
  fi
done

RUFF_ARGS=(check src tests)
if [[ "$FIX_MODE" == true ]]; then
  RUFF_ARGS=(check --fix src tests)
fi

if command -v uv >/dev/null 2>&1; then
  if uv run ruff "${RUFF_ARGS[@]}"; then
    exit 0
  fi
  echo "uv run ruff failed; falling back to local venv" >&2
fi

if [[ -x ".venv/bin/ruff" ]]; then
  .venv/bin/ruff "${RUFF_ARGS[@]}"
else
  echo "ruff not available in .venv; please install dependencies (uv sync)" >&2
  exit 1
fi
