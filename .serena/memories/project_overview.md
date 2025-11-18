# プロジェクト概要
- プロジェクト名: game-recommendation
- 目的: IGDB API から新着ゲームを取得し、ユーザーお気に入りに基づく類似ゲームをAIで算出してDiscord通知する。TyperベースCLIで完結。
- データ管理: SQLite3（単一DBファイル）。ゲーム本体・タグ・タグリンク・お気に入り・ゲーム埋め込みを管理し、スキーマは SQLAlchemy ORM＋Alembic で運用。
- 技術スタック: Python 3.11+, uv、typer、httpx、SQLAlchemy、Alembic、structlog、google-generativeai（Gemini）、Discord Webhook、pytest、ruff。CLIエントリポイントは `game-reco`（`game_recommendation.cli.app:main`）。IGDB 連携は `igdb-api-v4`、埋め込みは Gemini が標準。
- レイヤ構成: `src/game_recommendation` 配下に core（ドメイン・レコメンド）、infra（IGDB/Discord/AI/SQLite 抽象化）、cli（typer CLI）、shared（共通ユーティリティ）を配置。tests は core/infra/cli 向けにディレクトリ分割。
- 設定ファイル: `pyproject.toml` で依存とruff設定を定義、`.env.example` に IGDB/Discord/SQLite/Gemini の環境変数例を記載。`IGDB__APP_ACCESS_TOKEN` が未設定なら `IGDB__CLIENT_SECRET` を利用できる。