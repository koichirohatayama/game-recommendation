#!/usr/bin/env bash
set -euo pipefail

# Alembic マイグレーションを実行するヘルパー。
# 例: scripts/migrate.sh               # スキーマを最新へ
#     scripts/migrate.sh <revision>    # 指定リビジョンへ

REVISION="${1:-head}"

uv run alembic -c alembic.ini upgrade "${REVISION}"
