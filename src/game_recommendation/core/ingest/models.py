"""IGDB取り込み向け統合ドメインモデル。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from game_recommendation.infra.igdb.dto import IGDBGameDTO
from game_recommendation.shared.types import DTO

__all__ = [
    "GameTagPayload",
    "IngestedEmbedding",
    "EmbeddedGamePayload",
]


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _deduplicate_tags(tags: Sequence[GameTagPayload]) -> tuple[GameTagPayload, ...]:
    unique: dict[tuple[str, str], GameTagPayload] = {}
    for tag in tags:
        unique.setdefault(tag.identity, tag)
    return tuple(unique.values())


@dataclass(slots=True)
class GameTagPayload(DTO):
    """game_tags テーブル向けのタグ情報。"""

    slug: str
    label: str
    tag_class: str
    igdb_id: int | None = None

    def __post_init__(self) -> None:
        slug = _normalize_text(self.slug)
        label = _normalize_text(self.label)
        tag_class = _normalize_text(self.tag_class)
        if not slug or not label or not tag_class:
            msg = "slug/label/tag_classは必須"
            raise ValueError(msg)
        object.__setattr__(self, "slug", slug.lower())
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "tag_class", tag_class.lower())

    @property
    def identity(self) -> tuple[str, str]:
        return (self.slug, self.tag_class)

    def to_game_tag(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "tag_class": self.tag_class,
            "igdb_id": self.igdb_id,
        }


@dataclass(slots=True)
class IngestedEmbedding(DTO):
    """埋め込みベクトルおよびメタデータ。"""

    title_embedding: Sequence[float]
    description_embedding: Sequence[float]
    model: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    dimension: int | None = None

    def __post_init__(self) -> None:
        title = tuple(float(value) for value in self.title_embedding)
        description = tuple(float(value) for value in self.description_embedding)
        model = _normalize_text(self.model)
        if not model:
            msg = "modelは必須"
            raise ValueError(msg)
        dimension = self.dimension or len(title)
        if len(title) != len(description) or len(title) != dimension:
            msg = "title_embeddingとdescription_embeddingの次元が不一致"
            raise ValueError(msg)
        object.__setattr__(self, "title_embedding", title)
        object.__setattr__(self, "description_embedding", description)
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_game_embedding(
        self,
        game_id: str,
        *,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(extra_metadata or {})
        metadata.update(self.metadata)
        return {
            "game_id": str(game_id),
            "dimension": self.dimension,
            "title_embedding": self.title_embedding,
            "description_embedding": self.description_embedding,
            "embedding_metadata": metadata,
        }


@dataclass(slots=True)
class EmbeddedGamePayload(DTO):
    """IGDBゲームデータと周辺情報を束ねた入力モデル。"""

    igdb_game: IGDBGameDTO
    description: str | None = None
    checksum: str | None = None
    cover_url: str | None = None
    tags: Sequence[GameTagPayload] = field(default_factory=tuple)
    keywords: Sequence[str] = field(default_factory=tuple)
    embedding: IngestedEmbedding | None = None
    favorite: bool = False
    favorite_notes: str | None = None

    def __post_init__(self) -> None:
        description = _normalize_text(self.description) or _normalize_text(self.igdb_game.summary)
        if not description:
            description = self.igdb_game.name
        normalized_tags = _deduplicate_tags(self.tags)
        keywords = tuple(
            keyword.strip() for keyword in self.keywords if keyword and keyword.strip()
        )

        object.__setattr__(self, "description", description)
        object.__setattr__(self, "tags", normalized_tags)
        object.__setattr__(self, "keywords", keywords)
        object.__setattr__(self, "favorite_notes", _normalize_text(self.favorite_notes))

    @property
    def release_date(self) -> str | None:
        value = self.igdb_game.first_release_date
        if isinstance(value, datetime):
            return value.date().isoformat()
        return None

    def to_igdb_game(self) -> dict[str, Any]:
        tags_cache = json.dumps(
            {
                "tags": [tag.label for tag in self.tags],
                "tag_classes": [tag.tag_class for tag in self.tags],
                "keywords": list(self.keywords),
            }
        )
        return {
            "igdb_id": self.igdb_game.id,
            "slug": self.igdb_game.slug,
            "title": self.igdb_game.name,
            "description": self.description,
            "summary": self.igdb_game.summary,
            "release_date": self.release_date,
            "cover_url": self.cover_url,
            "checksum": self.checksum,
            "tags_cache": tags_cache,
        }

    def to_game_embedding(self) -> dict[str, Any]:
        if self.embedding is None:
            msg = "embeddingが指定されていません"
            raise ValueError(msg)
        metadata = {
            "title": self.igdb_game.name,
            "summary": self.igdb_game.summary,
            "tags": [tag.label for tag in self.tags],
            "tag_classes": [tag.tag_class for tag in self.tags],
            "keywords": list(self.keywords),
            "slug": self.igdb_game.slug,
        }
        return self.embedding.to_game_embedding(
            str(self.igdb_game.id),
            extra_metadata=metadata,
        )

    def to_game_tag(self) -> tuple[dict[str, Any], ...]:
        return tuple(tag.to_game_tag() for tag in self.tags)

    def to_game_tag_link(
        self,
        game_record_id: int,
        tag_id_lookup: Mapping[tuple[str, str], int],
    ) -> tuple[dict[str, int], ...]:
        links: list[dict[str, int]] = []
        for tag in self.tags:
            tag_id = tag_id_lookup.get(tag.identity)
            if tag_id is None:
                msg = f"tag_idが見つかりません: {tag.identity}"
                raise KeyError(msg)
            links.append({"game_id": game_record_id, "tag_id": tag_id})
        return tuple(links)

    def to_user_favorite_game(
        self,
        game_record_id: int,
        *,
        notes: str | None = None,
    ) -> dict[str, Any]:
        resolved_notes = _normalize_text(notes) or self.favorite_notes
        return {
            "game_id": game_record_id,
            "notes": resolved_notes,
        }
