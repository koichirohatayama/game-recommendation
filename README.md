# game-recommendation

IGDB からゲームを取得し、Gemini 埋め込みで類似度を計算、エージェントによるおすすめ判定と Discord 通知までを CLI で完結させるツールキット

## できること
- IGDB タイトル検索（`game-reco igdb search`）
- IGDB ID を指定した取り込み: ゲーム/タグ/タグリンク/埋め込み/お気に入りを SQLite に保存（`game-reco import`）
- お気に入りデータに基づくおすすめプロンプト生成: タグ・タイトル/ストーリー/サマリー埋め込み類似度を併用（`game-reco prompt generate`）
- コーディングエージェント（Codex CLI / Claude Code）での判定実行と JSON 出力（`game-reco recommend run`）
- リリース日を指定した一括判定と Discord Webhook 通知（`game-reco recommend-release`）

## 前提
- Python 3.11+
- uv
- SQLite3
- API キー: IGDB `CLIENT_ID`/`CLIENT_SECRET`、Discord Webhook、Gemini API Key

## セットアップ
1. 依存の同期: `uv sync`
2. 環境変数: `.env.example` をコピーして `.env` を作成し、IGDB/Discord/Gemini を設定
3. DB 初期化: `scripts/migrate.sh` で Alembic マイグレーションを適用

## CLI の使い方
- IGDB 検索: `uv run game-reco igdb search --title "<title>" --match search|contains|exact --limit 10 --output table|json`
- お気に入りデータ取り込み: `uv run game-reco import --igdb-ids 123,456 --dry-run --output table|json`
- おすすめプロンプト生成: `uv run game-reco prompt generate --igdb-id 123 --limit 3 --output-file prompt.txt`
- おすすめ判定: `uv run game-reco recommend run --igdb-id 123 --agent codex-cli|claude-code`
- 特定の日付にリリースされたゲームをおすすめ判定してDiscord通知: `uv run game-reco recommend-release --release-date YYYY-MM-DD --agent codex-cli|claude-code`
→ このCLIをcronなどでデイリーで呼び出せば毎日の通知が可能

## データモデルと構成
- テーブル: `igdb_games`（基本情報+summary）、`game_tags`/`game_tag_links`、`user_favorite_games`、`game_embeddings`（title/storyline/summary 各 embedding + metadata）
- core: IGDB レスポンスの取り込みビルダー、類似度計算、プロンプトビルダー
- infra: IGDB クライアント、Gemini 埋め込みサービス、SQLite DAO、Discord Webhook、エージェントランナー
- cli: Typer ベースの各コマンド（検索・取り込み・プロンプト生成・判定・リリースバッチ）
- scripts: lint/test 実行やマイグレーション補助

## 開発メモ
- format: `scripts/format.sh`
- lint: `scripts/lint.sh`
- テスト: `scripts/test.sh`
- マイグレーション: `scripts/migrate.sh`
- ログレベルや実行環境は `.env` の `LOG_LEVEL` / `ENVIRONMENT` で制御
