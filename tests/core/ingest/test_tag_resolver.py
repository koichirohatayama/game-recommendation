from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from game_recommendation.core.ingest.tag_resolver import TagResolver
from game_recommendation.infra.db.models import Base, GameTag
from game_recommendation.infra.db.repositories import SQLAlchemyGameTagRepository
from game_recommendation.infra.igdb.dto import IGDBTagDTO


def _make_tag_number(type_id: int, igdb_id: int) -> int:
    return (type_id << 28) | igdb_id


class FakeTagClient:
    def __init__(self, responses: dict[str, dict[int, IGDBTagDTO]]):
        self._responses = responses
        self.requests: list[tuple[str, list[int]]] = []

    def fetch_tags(self, *, tag_class: str, igdb_ids: Sequence[int]) -> Sequence[IGDBTagDTO]:
        self.requests.append((tag_class, list(igdb_ids)))
        available = self._responses.get(tag_class, {})
        return tuple(available[tag_id] for tag_id in igdb_ids if tag_id in available)


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, autoflush=False, expire_on_commit=False, future=True)


def test_resolve_uses_cached_tags(session_factory: sessionmaker) -> None:
    repo = SQLAlchemyGameTagRepository(session_factory)
    client = FakeTagClient(responses={})
    tag_id = 5
    tag_number = _make_tag_number(1, tag_id)

    with session_factory.begin() as session:
        session.add(GameTag(slug="shooter", label="Shooter", tag_class="genre", igdb_id=tag_id))

    resolver = TagResolver(repository=repo, igdb_client=client)
    result = resolver.resolve((tag_number,))

    assert result.is_ok
    resolved = result.unwrap()
    assert len(resolved) == 1
    assert resolved[0].slug == "shooter"
    assert client.requests == []


def test_resolve_fetches_and_caches_missing_tags(session_factory: sessionmaker) -> None:
    repo = SQLAlchemyGameTagRepository(session_factory)
    tag_id = 148
    tag_number = _make_tag_number(2, tag_id)
    client = FakeTagClient(
        responses={
            "keyword": {tag_id: IGDBTagDTO(id=tag_id, name="MOBA", slug="moba")},
        }
    )

    resolver = TagResolver(repository=repo, igdb_client=client)

    first = resolver.resolve((tag_number,))
    assert first.is_ok
    cached = first.unwrap()
    assert cached[0].label == "MOBA"
    assert len(client.requests) == 1

    with session_factory() as session:
        stored = (
            session.query(GameTag).filter_by(igdb_id=tag_id, tag_class="keyword", slug="moba").one()
        )
        assert stored.label == "MOBA"

    second = resolver.resolve((tag_number,))
    assert second.is_ok
    assert second.unwrap()[0].slug == "moba"
    assert len(client.requests) == 1
