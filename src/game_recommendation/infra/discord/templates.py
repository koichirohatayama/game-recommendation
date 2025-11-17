"""Discord 通知用のメッセージテンプレート。"""

from __future__ import annotations

from game_recommendation.core.similarity.dto import SimilarityMatch, SimilarityResult

DISCORD_MESSAGE_LIMIT = 1800


def truncate_text(value: str, limit: int = 300) -> str:
    """長文を Discord 用に短縮する。"""

    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def chunk_message(content: str, *, limit: int = DISCORD_MESSAGE_LIMIT) -> tuple[str, ...]:
    """Discord の文字数制限に合わせて分割する。"""

    if limit <= 0:
        msg = "limit must be positive"
        raise ValueError(msg)
    if not content:
        return tuple()

    chunks: list[str] = []
    buffer = ""

    for line in content.splitlines():
        if buffer and len(buffer) + 1 + len(line) > limit:
            chunks.append(buffer)
            buffer = ""

        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]

        buffer = line if not buffer else f"{buffer}\n{line}"

    if buffer:
        chunks.append(buffer)

    return tuple(chunks)


def _build_match_block(match: SimilarityMatch, rank: int) -> str:
    candidate = match.candidate
    title = candidate.title or "タイトル未設定"
    lines = [
        f"{rank}. {title} (ID: {candidate.game_id})",
        (
            f"- 類似度: {match.score:.3f} / ベース: {match.base_score:.3f} "
            f"/ 距離: {match.distance:.3f}"
        ),
    ]

    detail_parts: list[str] = []
    if candidate.genres:
        detail_parts.append(f"ジャンル: {', '.join(candidate.genres)}")
    if candidate.tags:
        detail_parts.append(f"タグ: {', '.join(candidate.tags)}")
    if detail_parts:
        lines.append(f"- {' | '.join(detail_parts)}")

    if candidate.summary:
        shortened = truncate_text(candidate.summary, 280)
        lines.append(f"- 概要: {shortened}")

    if match.reasons:
        lines.append(f"- 判定根拠: {', '.join(match.reasons)}")

    return "\n".join(lines)


def build_recommendation_messages(
    result: SimilarityResult,
    *,
    limit: int = DISCORD_MESSAGE_LIMIT,
) -> tuple[str, ...]:
    """推薦結果を Discord 投稿用メッセージへ整形する。"""

    lines: list[str] = [
        f"🎮 推薦結果 ({result.embedding_model})",
        f"クエリ: {result.query.title}",
    ]

    if result.query.focus_keywords:
        lines.append(f"注目キーワード: {', '.join(result.query.focus_keywords)}")
    if result.query.tags:
        lines.append(f"タグ: {', '.join(result.query.tags)}")
    if result.query.genres:
        lines.append(f"ジャンル: {', '.join(result.query.genres)}")

    lines.append("")

    for index, match in enumerate(result.matches):
        lines.append(_build_match_block(match, index + 1))

    content = "\n\n".join(lines).strip()
    return chunk_message(content, limit=limit)


__all__ = [
    "DISCORD_MESSAGE_LIMIT",
    "build_recommendation_messages",
    "chunk_message",
    "truncate_text",
]
