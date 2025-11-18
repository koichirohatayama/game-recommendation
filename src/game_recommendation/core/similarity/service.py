"""類似ゲーム検索サービス。"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from game_recommendation.core.similarity.dto import (
    EmbeddedGameContext,
    SimilarityMatch,
    SimilarityQuery,
    SimilarityResult,
)
from game_recommendation.infra.db.embedding_repository import (
    EmbeddingRepository,
    GameEmbeddingSearchResult,
)
from game_recommendation.infra.embeddings.base import (
    EmbeddingJob,
    EmbeddingServiceError,
    EmbeddingServiceProtocol,
)
from game_recommendation.shared.exceptions import BaseAppError, DomainError, Result
from game_recommendation.shared.logging import get_logger
from game_recommendation.shared.types import utc_now

try:  # pragma: no cover - 型ヒント専用
    from structlog.stdlib import BoundLogger
except Exception:  # pragma: no cover
    BoundLogger = object  # type: ignore[assignment]

__all__ = ["SimilarityService", "SimilarityServiceError"]


_WORD_PATTERN = re.compile(r"[\w']+", re.UNICODE)


class SimilarityServiceError(DomainError):
    """類似ゲーム算出時のエラー。"""

    default_message = "類似ゲームの算出に失敗しました"


@dataclass(slots=True)
class SimilarityService:
    """埋め込み検索と補正スコアリングを担うドメインサービス。"""

    embedding_service: EmbeddingServiceProtocol
    repository: EmbeddingRepository
    max_limit: int = 20
    min_score_threshold: float = 0.05
    logger: BoundLogger = field(
        default_factory=lambda: get_logger(__name__, component="similarity-core")
    )

    def find_similar(
        self, query: SimilarityQuery
    ) -> Result[SimilarityResult, SimilarityServiceError]:
        """入力 DTO を基に類似ゲームを検索し、Result で返す。"""

        limit = min(query.limit, self.max_limit)
        job = self._build_job(query)
        try:
            embedding = self.embedding_service.embed(job)
        except EmbeddingServiceError as exc:
            return self._fail("embedding_failed", exc)
        except Exception as exc:  # noqa: BLE001 - 原因追跡のためにそのまま保持
            return self._fail("embedding_unexpected_error", exc)

        fetch_limit = max(limit * 2, limit)
        try:
            candidates = self.repository.search_similar(embedding.values, limit=fetch_limit)
        except BaseAppError as exc:
            return self._fail("repository_failed", exc)
        except Exception as exc:  # noqa: BLE001
            return self._fail("repository_unexpected_error", exc)

        filtered = self._filter_results(query, candidates)
        matches: list[SimilarityMatch] = []
        for record in filtered:
            profile = EmbeddedGameContext.from_metadata(record.game_id, record.metadata)
            match = self._score_candidate(query, record, profile)
            if match.score < self.min_score_threshold:
                continue
            matches.append(match)
            if len(matches) >= limit:
                break

        matches.sort(key=lambda item: item.score, reverse=True)
        result = SimilarityResult(
            query=query,
            matches=tuple(matches),
            embedding_model=embedding.model,
            computed_at=utc_now(),
        )

        self.logger.info(
            "similarity_completed",
            query_title=query.title,
            match_count=len(matches),
            limit=limit,
            embedding_model=embedding.model,
            top_match=matches[0].candidate.game_id if matches else None,
        )
        return Result.ok(result)

    def _fail(
        self, event: str, error: Exception
    ) -> Result[SimilarityResult, SimilarityServiceError]:
        self.logger.error(
            event,
            error_type=error.__class__.__name__,
            message=str(error),
        )
        wrapped = SimilarityServiceError(str(error))
        return Result.err(wrapped)

    def _build_job(self, query: SimilarityQuery) -> EmbeddingJob:
        sections = [f"Title: {query.title.strip()}"]
        if query.summary:
            sections.append(f"Summary: {query.summary.strip()}")
        if query.genres:
            sections.append(f"Genres: {', '.join(query.genres)}")
        if query.tags:
            sections.append(f"Tags: {', '.join(query.tags)}")
        if query.focus_keywords:
            sections.append(f"Keywords: {', '.join(query.focus_keywords)}")
        content = "\n".join(sections)
        metadata = {
            "title": query.title,
            "summary": query.summary,
            "genres": list(query.genres),
            "tags": list(query.tags),
            "keywords": list(query.focus_keywords),
            "game_id": query.game_id,
        }
        return EmbeddingJob(content=content, metadata=metadata)

    def _filter_results(
        self,
        query: SimilarityQuery,
        results: Sequence[GameEmbeddingSearchResult],
    ) -> list[GameEmbeddingSearchResult]:
        excluded = set(query.excluded_game_ids)
        if query.game_id:
            excluded.add(query.game_id.lower())

        filtered: list[GameEmbeddingSearchResult] = []
        seen: set[str] = set()
        for record in results:
            identifier = str(record.game_id).lower()
            if identifier in excluded or identifier in seen:
                continue
            filtered.append(record)
            seen.add(identifier)
        return filtered

    def _score_candidate(
        self,
        query: SimilarityQuery,
        record: GameEmbeddingSearchResult,
        profile: EmbeddedGameContext,
    ) -> SimilarityMatch:
        base_score = self._base_similarity(record.distance)
        adjusted = base_score
        reasons: list[str] = []

        tag_bonus, tag_reason = self._tag_bonus(query, profile)
        if tag_bonus:
            adjusted += tag_bonus
            if tag_reason:
                reasons.append(tag_reason)

        genre_bonus, genre_reason = self._genre_bonus(query, profile)
        if genre_bonus:
            adjusted += genre_bonus
            if genre_reason:
                reasons.append(genre_reason)

        keyword_bonus, keyword_reason = self._keyword_bonus(query, profile)
        if keyword_bonus:
            adjusted += keyword_bonus
            if keyword_reason:
                reasons.append(keyword_reason)

        summary_bonus, summary_reason = self._summary_bonus(query.summary, profile.summary)
        if summary_bonus:
            adjusted += summary_bonus
            if summary_reason:
                reasons.append(summary_reason)

        coverage_penalty, coverage_reason = self._coverage_penalty(query, profile)
        if coverage_penalty:
            adjusted -= coverage_penalty
            if coverage_reason:
                reasons.append(coverage_reason)

        final_score = self._clamp(adjusted)
        return SimilarityMatch(
            candidate=profile,
            score=final_score,
            base_score=base_score,
            distance=record.distance,
            reasons=tuple(reasons),
        )

    def _base_similarity(self, distance: float) -> float:
        if math.isnan(distance) or distance < 0:
            return self.min_score_threshold
        return 1.0 / (1.0 + distance)

    def _tag_bonus(
        self, query: SimilarityQuery, profile: EmbeddedGameContext
    ) -> tuple[float, str | None]:
        query_tags = set(query.normalized_tags)
        if not query_tags:
            return 0.0, None
        overlap = query_tags & profile.normalized_tags
        if not overlap:
            return 0.0, None
        ratio = len(overlap) / len(query_tags)
        bonus = min(0.2, 0.05 + (0.15 * ratio))
        reason = f"tag_overlap:{','.join(sorted(overlap))}"
        return bonus, reason

    def _genre_bonus(
        self, query: SimilarityQuery, profile: EmbeddedGameContext
    ) -> tuple[float, str | None]:
        query_genres = set(query.normalized_genres)
        if not query_genres:
            return 0.0, None
        overlap = query_genres & profile.normalized_genres
        if not overlap:
            return 0.0, None
        ratio = len(overlap) / len(query_genres)
        bonus = min(0.15, 0.03 + (0.12 * ratio))
        reason = f"genre_overlap:{','.join(sorted(overlap))}"
        return bonus, reason

    def _keyword_bonus(
        self, query: SimilarityQuery, profile: EmbeddedGameContext
    ) -> tuple[float, str | None]:
        keywords = set(query.normalized_keywords)
        if not keywords:
            return 0.0, None
        candidate = profile.normalized_keywords | profile.normalized_tags
        if not candidate:
            return 0.0, None
        overlap = keywords & candidate
        if not overlap:
            return 0.0, None
        ratio = len(overlap) / len(keywords)
        bonus = min(0.1, 0.02 + (0.08 * ratio))
        reason = f"keyword_overlap:{','.join(sorted(overlap))}"
        return bonus, reason

    def _summary_bonus(
        self, query_summary: str | None, candidate_summary: str | None
    ) -> tuple[float, str | None]:
        if not query_summary or not candidate_summary:
            return 0.0, None
        query_tokens = self._tokenize(query_summary)
        candidate_tokens = self._tokenize(candidate_summary)
        if not query_tokens or not candidate_tokens:
            return 0.0, None
        overlap = query_tokens & candidate_tokens
        if not overlap:
            return 0.0, None
        ratio = len(overlap) / len(query_tokens)
        bonus = min(0.2, 0.1 * ratio + 0.02)
        reason = f"summary_overlap:{len(overlap)}"
        return bonus, reason

    def _coverage_penalty(
        self,
        query: SimilarityQuery,
        profile: EmbeddedGameContext,
    ) -> tuple[float, str | None]:
        penalties: list[tuple[float, str]] = []
        if query.tags and not profile.tags:
            penalties.append((0.03, "missing_tags"))
        if query.genres and not profile.genres:
            penalties.append((0.03, "missing_genres"))
        if query.summary and not profile.summary:
            penalties.append((0.05, "missing_summary"))
        if not penalties:
            return 0.0, None
        total = sum(value for value, _ in penalties)
        reason = ",".join(label for _, label in penalties)
        return total, f"penalty:{reason}"

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _tokenize(self, text: str) -> set[str]:
        return {token for token in _WORD_PATTERN.findall(text.lower()) if token}
