# ディレクトリ構造メモ
- `scripts/`: lint/format や開発補助スクリプト置き場。`migrate.sh` で Alembic マイグレーションを実行。
- `src/game_recommendation/core/`: ドメイン・レコメンド・ユーザープロファイルの純粋ロジック。
- `src/game_recommendation/infra/`: IGDB、Discord、AI埋め込み、SQLite3 のクライアント抽象化。`infra/db/` 直下は SQLAlchemy ORM と Alembic で管理。`infra/db/models.py` に全テーブルのモデル、`infra/db/embedding_repository.py` に埋め込みDAO、`infra/db/alembic` にマイグレーションを配置し、`alembic.ini` と `scripts/migrate.sh` で適用。`infra/embeddings/` にサービスレジストリと Gemini 実装、`infra/igdb/` に IGDB クライアント・DTO を配置。
- `src/game_recommendation/cli/`: typer ベース CLI と個別コマンド枠（新着取得、レコメンド通知、SQLite 初期化、バッチ）。
- `src/game_recommendation/shared/`: 設定読み込み、共通型、ユーティリティ。
- `tests/`: core/infra/cli それぞれのテスト枠。