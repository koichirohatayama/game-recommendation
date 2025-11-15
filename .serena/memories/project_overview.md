# プロジェクト概要
- プロジェクト名: game-recommendation
- 目的: IGDB API から新着ゲームを取得し、ユーザーお気に入りに基づく類似ゲームをAIで算出してDiscord通知し、Streamlitダッシュボードで可視化する。
- データ管理: SQLite3（単一DBファイル）。ゲーム本体・タグ・タグリンク・お気に入り・ゲーム埋め込み（`game_embeddings`）をマイグレーションで作成。
- 技術スタック: Python 3.11+, uv、typer、Streamlit、httpx、python-dotenv、pytest、ruff。CLIエントリポイントは `game-reco`（`game_recommendation.cli.app:main`）。IGDB 連携は `igdb-api-v4`、埋め込みは `google-generativeai`/Gemini が標準。
- レイヤ構成: `src/game_recommendation` 配下に core（ドメイン・レコメンド）、infra（IGDB/Discord/AI/SQLite 抽象化）、cli（typer CLI）、web（Streamlit pages/components）、shared（共通ユーティリティ）を配置。tests は core/infra/cli 向けにディレクトリ分割。
- 設定ファイル: `pyproject.toml` で依存とruff設定を定義、`.env.example` で IGDB/Discord/DB/Gemini の環境変数を提示。`IGDB__APP_ACCESS_TOKEN` が未設定なら `IGDB__CLIENT_SECRET` を利用できる。