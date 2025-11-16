from __future__ import annotations

import typer

from game_recommendation.cli.commands import igdb
from game_recommendation.shared.logging import configure_logging

app = typer.Typer(help="ゲームレコメンドツールのCLI")

app.add_typer(igdb.app, name="igdb", help="IGDB 関連の操作")


def main() -> None:
    """エントリポイント。"""

    configure_logging()
    app()


if __name__ == "__main__":  # pragma: no cover - CLI エントリ
    main()
