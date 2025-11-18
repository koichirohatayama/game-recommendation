"""推薦プロンプトの組み立てを行う。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from game_recommendation.core.ingest.models import EmbeddedGamePayload
from game_recommendation.shared.types import DTO

DEFAULT_TEMPLATE_NAME = "recommendation.txt.j2"
OUTPUT_SCHEMA_EXAMPLE = '{"recommend": <bool>, "reason": "<string>"}'
_TEMPLATES_DIR = Path(__file__).with_name("templates")
_TARGET_DESCRIPTION_LIMIT = 320
_SIMILAR_DESCRIPTION_LIMIT = 200


@dataclass(slots=True)
class RecommendationDecision(DTO):
    """判定結果のJSONスキーマを表す。"""

    recommend: bool
    reason: str


@dataclass(slots=True)
class SimilarGameExample(DTO):
    """類似結果の1件分。"""

    game: EmbeddedGamePayload
    score: float | None = None
    note: str | None = None

    def to_prompt_entry(self, *, max_description_length: int) -> str:
        score_label = (
            f"類似度スコア: {self.score:.3f}" if self.score is not None else "類似度スコア: 不明"
        )
        annotations: list[str] = []
        if self.note:
            annotations.append(self.note)
        if annotations:
            score_label = f"{score_label} ({'; '.join(annotations)})"

        overview = self.game.to_prompt_string(max_description_length=max_description_length)
        return "\n".join((score_label, overview))


@dataclass(slots=True)
class RecommendationPromptInput(DTO):
    """プロンプト生成に必要な入力。"""

    target: EmbeddedGamePayload
    tag_similar: Sequence[SimilarGameExample] = field(default_factory=tuple)
    title_similar: Sequence[SimilarGameExample] = field(default_factory=tuple)
    storyline_similar: Sequence[SimilarGameExample] = field(default_factory=tuple)
    summary_similar: Sequence[SimilarGameExample] = field(default_factory=tuple)


@dataclass(slots=True)
class RecommendationPromptSections(DTO):
    """生成済みセクションのまとまり。"""

    target_overview: str
    tag_similar: tuple[str, ...]
    title_similar: tuple[str, ...]
    storyline_similar: tuple[str, ...]
    summary_similar: tuple[str, ...]


@dataclass(slots=True)
class RecommendationPromptResult(DTO):
    """生成されたプロンプトと内容。"""

    prompt: str
    template_name: str
    sections: RecommendationPromptSections


class RecommendationPromptBuilder:
    """推薦判定用のプロンプトを生成するビルダー。"""

    def __init__(
        self,
        templates_dir: Path | None = None,
        *,
        target_description_length: int = _TARGET_DESCRIPTION_LIMIT,
        similar_description_length: int = _SIMILAR_DESCRIPTION_LIMIT,
    ) -> None:
        self.templates_dir = Path(templates_dir) if templates_dir else _TEMPLATES_DIR
        self.target_description_length = target_description_length
        self.similar_description_length = similar_description_length

    def build(
        self, data: RecommendationPromptInput, *, template_name: str | None = None
    ) -> RecommendationPromptResult:
        path = self._resolve_template(template_name or DEFAULT_TEMPLATE_NAME)
        template = path.read_text(encoding="utf-8")
        sections = self._build_sections(data)

        prompt = template.format(
            output_schema=OUTPUT_SCHEMA_EXAMPLE,
            target_overview=sections.target_overview,
            tag_similar_block=self._join_section(sections.tag_similar),
            tag_similar_count=len(sections.tag_similar),
            title_similar_block=self._join_section(sections.title_similar),
            title_similar_count=len(sections.title_similar),
            storyline_similar_block=self._join_section(sections.storyline_similar),
            storyline_similar_count=len(sections.storyline_similar),
            summary_similar_block=self._join_section(sections.summary_similar),
            summary_similar_count=len(sections.summary_similar),
        ).strip()

        return RecommendationPromptResult(prompt=prompt, template_name=path.name, sections=sections)

    def _build_sections(self, data: RecommendationPromptInput) -> RecommendationPromptSections:
        target_overview = data.target.to_prompt_string(
            max_description_length=self.target_description_length
        )
        tag_similar = self._render_similar(data.tag_similar)
        title_similar = self._render_similar(data.title_similar)
        storyline_similar = self._render_similar(data.storyline_similar)
        summary_similar = self._render_similar(data.summary_similar)
        return RecommendationPromptSections(
            target_overview=target_overview,
            tag_similar=tag_similar,
            title_similar=title_similar,
            storyline_similar=storyline_similar,
            summary_similar=summary_similar,
        )

    def _render_similar(self, examples: Sequence[SimilarGameExample]) -> tuple[str, ...]:
        return tuple(
            example.to_prompt_entry(max_description_length=self.similar_description_length)
            for example in examples
        )

    def _resolve_template(self, name: str) -> Path:
        path = self.templates_dir / name
        if not path.exists():
            msg = f"テンプレートが見つかりません: {path}"
            raise FileNotFoundError(msg)
        return path

    @staticmethod
    def _join_section(lines: Sequence[str]) -> str:
        return "\n\n".join(lines) if lines else "なし"
