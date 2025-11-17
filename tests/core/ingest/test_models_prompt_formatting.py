"""EmbeddedGamePayload.to_prompt_string のテスト。"""

from __future__ import annotations

from datetime import UTC, datetime

from game_recommendation.core.ingest.models import (
    EmbeddedGamePayload,
    GameTagPayload,
)
from game_recommendation.infra.igdb.dto import IGDBGameDTO


def _igdb_game(name: str = "Sample Game", summary: str | None = None) -> IGDBGameDTO:
    return IGDBGameDTO(
        id=123,
        name=name,
        slug="sample-game",
        summary=summary,
        storyline=summary,
        first_release_date=datetime(2024, 1, 2, tzinfo=UTC),
        cover_image_id="cover123",
        platforms=(6,),
        category=0,
        tags=(10, 20),
    )


def test_to_prompt_string_basic_output() -> None:
    """基本的な出力形式を確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="A hero saves the world.",
        summary="A short summary.",
        tags=[
            GameTagPayload(slug="rpg", label="RPG", tag_class="genre", igdb_id=10),
            GameTagPayload(slug="fantasy", label="Fantasy", tag_class="keyword"),
        ],
        keywords=("hero", "adventure"),
    )

    result = payload.to_prompt_string()

    assert "タイトル: Sample Game" in result
    assert "ストーリー: A hero saves the world." in result
    assert "サマリー: A short summary." in result
    assert "タグ: RPG, Fantasy" in result
    assert "キーワード: hero, adventure" in result


def test_to_prompt_string_handles_newlines_in_description() -> None:
    """説明文内の改行が適切にサニタイズされることを確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="First line.\nSecond line.\r\nThird line.",
        summary="Summary text.",
    )

    result = payload.to_prompt_string()

    assert "ストーリー: First line. Second line. Third line." in result
    assert "\nストーリー:" in result  # フィールド間の改行は保持
    assert "First line.\nSecond" not in result  # 説明文内の改行は除去


def test_to_prompt_string_handles_multiple_spaces() -> None:
    """連続した空白が1つにまとめられることを確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="Too    many     spaces   here.",
        summary="Summary text.",
    )

    result = payload.to_prompt_string()

    assert "ストーリー: Too many spaces here." in result


def test_to_prompt_string_trims_long_description() -> None:
    """長文がトリミングされることを確認する。"""
    long_text = "word " * 200  # 200単語以上の長文
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline=long_text,
        summary=long_text,
    )

    result = payload.to_prompt_string(max_description_length=100)

    # 説明フィールドから該当箇所を抽出
    lines = result.split("\n")
    storyline_line = next(line for line in lines if line.startswith("ストーリー: "))
    storyline_content = storyline_line.replace("ストーリー: ", "")

    assert len(storyline_content) <= 104  # 100文字 + "..." (3文字) + バッファ
    assert storyline_content.endswith("...")


def test_to_prompt_string_handles_missing_description() -> None:
    """説明文が欠損している場合の処理を確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(summary=None),
        storyline=None,
        summary=None,
    )

    result = payload.to_prompt_string()

    assert "ストーリー: Sample Game" in result
    assert "サマリー: Sample Game" in result


def test_to_prompt_string_handles_empty_tags() -> None:
    """タグが空の場合の処理を確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="Test game",
        summary="Test game",
        tags=[],
    )

    result = payload.to_prompt_string()

    assert "タグ: なし" in result


def test_to_prompt_string_handles_empty_keywords() -> None:
    """キーワードが空の場合の処理を確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline="Test game",
        summary="Test game",
        keywords=[],
    )

    result = payload.to_prompt_string()

    assert "キーワード: なし" in result


def test_to_prompt_string_respects_custom_max_length() -> None:
    """カスタムの最大文字数が適用されることを確認する。"""
    long_text = "x" * 1000
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(),
        storyline=long_text,
        summary=long_text,
    )

    result = payload.to_prompt_string(max_description_length=50)

    lines = result.split("\n")
    storyline_line = next(line for line in lines if line.startswith("ストーリー: "))
    description_content = storyline_line.replace("ストーリー: ", "")

    assert len(description_content) <= 54  # 50 + "..." (3文字) + バッファ


def test_to_prompt_string_complete_example() -> None:
    """完全なデータでの出力例を確認する。"""
    payload = EmbeddedGamePayload(
        igdb_game=_igdb_game(name="The Legend of Heroes", summary="An epic JRPG adventure"),
        storyline="A story-driven JRPG with turn-based combat.\nFeatures a vast world.",
        summary="An epic JRPG adventure",
        tags=[
            GameTagPayload(slug="jrpg", label="JRPG", tag_class="genre"),
            GameTagPayload(slug="turn-based", label="Turn-Based", tag_class="gameplay"),
        ],
        keywords=("story", "combat", "world"),
    )

    result = payload.to_prompt_string()

    expected_lines = [
        "タイトル: The Legend of Heroes",
        "ストーリー: A story-driven JRPG with turn-based combat. Features a vast world.",
        "サマリー: An epic JRPG adventure",
        "タグ: JRPG, Turn-Based",
        "キーワード: story, combat, world",
    ]

    for expected in expected_lines:
        assert expected in result
