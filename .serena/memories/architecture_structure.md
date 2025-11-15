# ディレクトリ構造メモ
- `scripts/`: lint/format や開発補助スクリプト置き場。
- `src/game_recommendation/core/`: ドメイン・レコメンド・ユーザープロファイルの純粋ロジック。
- `src/game_recommendation/infra/`: IGDB、Discord、AI埋め込み、SQLite3 のクライアント抽象化。`infra/db/sqlite_vec.py` がマイグレーションと sqlite-vec DAO を提供し、`infra/embeddings/` にサービスレジストリと Gemini 実装、`infra/igdb/` に IGDB クライアント・DTO を配置。
- `src/game_recommendation/cli/` と `cli/commands/`: typer ベース CLI と個別コマンド枠（新着取得、レコメンド通知、SQLite 初期化、バッチ）。
- `src/game_recommendation/web/`: Streamlit エントリと共通UI。`pages/` は新着/レコメンド/ユーザー管理ページ、`components/` はレイアウト/UI部品。
- `src/game_recommendation/shared/`: 設定読み込み、共通型、ユーティリティ。
- `tests/`: core/infra/cli それぞれのテスト枠。