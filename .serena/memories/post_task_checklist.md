# タスク完了時のチェック
1. `uv run ruff format src tests` で整形。
2. `uv run ruff check src tests` で lint を通す。
3. 影響範囲に応じて `uv run pytest` や対象モジュールの Streamlit/CLI を動作確認。
4. `.env` 必須項目（IGDB/Discord/STORAGE_PATH）が揃っているかを確認し、機微情報をコミットしない。