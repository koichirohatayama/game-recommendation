# よく使うコマンド
- `uv sync` – pyproject.toml の依存をローカル環境へ同期。
- `uv run ruff check src tests` – Ruff lint 実行。
- `uv run ruff format src tests` – Ruff formatter でコード整形。
- `uv run pytest` – テストスイート実行。
- `uv run game-reco ...` – typer ベース CLI エントリ（game_recommendation.cli.app:main）を起動。
- `uv run streamlit run src/game_recommendation/web/app.py` – Streamlit ダッシュボード起動（app.py などエントリを実装後）。