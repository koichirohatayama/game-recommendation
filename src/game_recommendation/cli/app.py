from __future__ import annotations

import typer

from game_recommendation.cli.commands import (
    igdb,
    import_games,
    prompt,
    recommend,
    recommend_release,
)
from game_recommendation.shared.logging import configure_logging

app = typer.Typer(help="ゲームレコメンドツールのCLI")

app.add_typer(igdb.app, name="igdb", help="IGDB 関連の操作")
app.add_typer(import_games.app, name="import", help="IGDB ID を指定した取り込み")
app.add_typer(prompt.app, name="prompt", help="判定用プロンプト生成")
app.add_typer(recommend.app, name="recommend", help="判定プロンプト生成とエージェント実行")
app.add_typer(
    recommend_release.app,
    name="recommend-release",
    help="リリース日を指定した推薦と通知",
)


def main() -> None:
    """エントリポイント。"""

    configure_logging()
    app()


if __name__ == "__main__":  # pragma: no cover - CLI エントリ
    main()
