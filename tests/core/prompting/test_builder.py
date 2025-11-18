from pathlib import Path

from game_recommendation.core.ingest.models import EmbeddedGamePayload, GameTagPayload
from game_recommendation.core.prompting import (
    DEFAULT_TEMPLATE_NAME,
    RecommendationPromptBuilder,
    RecommendationPromptInput,
    SimilarGameExample,
)
from game_recommendation.infra.igdb.dto import IGDBGameDTO


def _payload(
    game_id: int,
    name: str,
    *,
    summary: str = "",
    favorite: bool = False,
) -> EmbeddedGamePayload:
    return EmbeddedGamePayload(
        igdb_game=IGDBGameDTO(
            id=game_id,
            name=name,
            slug=name.lower().replace(" ", "-"),
            summary=summary or f"Summary for {name}",
            storyline=summary or f"Summary for {name}",
        ),
        storyline=summary or f"Description for {name}",
        summary=summary or f"Summary for {name}",
        tags=(GameTagPayload(slug="adventure", label="Adventure", tag_class="genre"),),
        keywords=("story", "action"),
        favorite=favorite,
    )


def test_build_prompt_includes_sections() -> None:
    target = _payload(1, "New Arrival", summary="New JRPG with tactical battles")
    tag_match = SimilarGameExample(
        game=_payload(2, "Tag Neighbor", summary="Shares several tags"),
        score=0.82,
        note="タグ一致",
    )
    title_match = SimilarGameExample(
        game=_payload(3, "Title Twin", summary="Similar title wording"),
        score=0.74,
    )
    storyline_match = SimilarGameExample(
        game=_payload(4, "Lore Mate", favorite=True),
        note="長文類似",
    )
    summary_match = SimilarGameExample(
        game=_payload(5, "Digest Friend", summary="Short digest"),
        score=0.55,
    )

    builder = RecommendationPromptBuilder()
    data = RecommendationPromptInput(
        target=target,
        tag_similar=(tag_match,),
        title_similar=(title_match,),
        storyline_similar=(storyline_match,),
        summary_similar=(summary_match,),
    )

    result = builder.build(data)

    assert result.template_name == DEFAULT_TEMPLATE_NAME
    assert (
        "目的: 新着ゲームがユーザーの好みに合うかを、複合的な類似指標に基づいて判定する。"
        in result.prompt
    )
    assert target.igdb_game.name in result.prompt
    assert "類似結果: タグ類似 上位1件" in result.prompt
    assert "類似度スコア: 0.820" in result.prompt
    assert result.sections.tag_similar[0].startswith("類似度スコア: 0.820")
    assert "類似結果: ストーリー埋め込み 上位1件" in result.prompt
    assert "類似結果: サマリー埋め込み 上位1件" in result.prompt


def test_build_prompt_switches_template(tmp_path: Path) -> None:
    target = _payload(10, "Template Switch")
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    custom_template = template_dir / "custom.txt.j2"
    custom_template.write_text(
        "カスタムテンプレート\n{target_overview}\n{tag_similar_block}\n",
        encoding="utf-8",
    )

    builder = RecommendationPromptBuilder(templates_dir=template_dir)
    data = RecommendationPromptInput(target=target)

    result = builder.build(data, template_name="custom.txt.j2")

    assert result.template_name == "custom.txt.j2"
    assert result.prompt.startswith("カスタムテンプレート")
    assert "なし" in result.prompt
