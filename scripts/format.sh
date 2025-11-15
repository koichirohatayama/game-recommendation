#!/usr/bin/env bash
set -euo pipefail

CHECK_MODE=false
for arg in "$@"; do
  if [[ "$arg" == "--check" ]]; then
    CHECK_MODE=true
  else
    echo "Unknown argument: $arg" >&2
    exit 1
  fi

done

if [[ "$CHECK_MODE" == true ]]; then
  uv run ruff format --check src tests
else
  uv run ruff format src tests
fi
