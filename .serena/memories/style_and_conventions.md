# コードスタイルと設計指針
- Python 3.11 を前提。PEP 484 型ヒントと dataclass などを用い、core 層にドメインロジックを集約する。
- Ruff 設定: line-length=100、target-version=py311。lintは E/F/I/B/UP を有効化、ignore なし。
- フォーマッタ設定: ダブルクォート、スペースインデント、LF 改行に統一。
- レイヤリング: core は純粋ロジック、infra が外部API/SQLiteを抽象化、CLI/Web からは shared 経由で設定読み込みを行う。infra 以外から直接 SQLite/HTTP へアクセスしない。
- CLI (typer)・tests でも src/game_recommendation 以下の構造を崩さない。