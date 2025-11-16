"""GameTagモデルのテスト"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from game_recommendation.infra.db.models import Base, GameTag


@pytest.fixture
def db_session():
    """テスト用のインメモリデータベースセッションを作成"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def test_game_tag_with_class_and_igdb_id(db_session: Session):
    """tag_classとigdb_idを持つGameTagを作成できることを確認"""
    tag = GameTag(
        slug="action",
        label="Action",
        tag_class="genre",
        igdb_id=4,
    )
    db_session.add(tag)
    db_session.commit()

    # データベースから取得
    retrieved = db_session.query(GameTag).filter_by(slug="action", tag_class="genre").first()
    assert retrieved is not None
    assert retrieved.label == "Action"
    assert retrieved.tag_class == "genre"
    assert retrieved.igdb_id == 4


def test_game_tag_unique_constraint_slug_class(db_session: Session):
    """同じslugとtag_classの組み合わせは一意である必要がある"""
    tag1 = GameTag(slug="action", label="Action", tag_class="genre", igdb_id=4)
    db_session.add(tag1)
    db_session.commit()

    # 同じslugとtag_classで別のレコードを追加しようとするとエラー
    tag2 = GameTag(slug="action", label="Action", tag_class="genre", igdb_id=5)
    db_session.add(tag2)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_game_tag_different_class_same_slug(db_session: Session):
    """同じslugでも異なるtag_classなら登録可能"""
    tag1 = GameTag(slug="action", label="Action Genre", tag_class="genre", igdb_id=4)
    tag2 = GameTag(slug="action", label="Action Keyword", tag_class="keyword", igdb_id=100)

    db_session.add(tag1)
    db_session.add(tag2)
    db_session.commit()

    # 両方とも取得できる
    tags = db_session.query(GameTag).filter_by(slug="action").all()
    assert len(tags) == 2
    assert {tag.tag_class for tag in tags} == {"genre", "keyword"}


def test_game_tag_unique_constraint_igdb_id_class(db_session: Session):
    """同じigdb_idとtag_classの組み合わせは一意である必要がある"""
    tag1 = GameTag(slug="action", label="Action", tag_class="genre", igdb_id=4)
    db_session.add(tag1)
    db_session.commit()

    # 同じigdb_idとtag_classで別のレコードを追加しようとするとエラー
    tag2 = GameTag(slug="action-2", label="Action", tag_class="genre", igdb_id=4)
    db_session.add(tag2)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_game_tag_without_igdb_id(db_session: Session):
    """igdb_idなしでもGameTagを作成できる"""
    tag = GameTag(
        slug="custom-tag",
        label="Custom Tag",
        tag_class="custom",
    )
    db_session.add(tag)
    db_session.commit()

    retrieved = db_session.query(GameTag).filter_by(slug="custom-tag").first()
    assert retrieved is not None
    assert retrieved.igdb_id is None
    assert retrieved.tag_class == "custom"


def test_game_tag_all_classes(db_session: Session):
    """各種tag_classでGameTagを作成できることを確認"""
    classes = ["genre", "keyword", "theme", "franchise", "collection"]

    for i, tag_class in enumerate(classes):
        tag = GameTag(
            slug=f"{tag_class}-test",
            label=f"Test {tag_class.title()}",
            tag_class=tag_class,
            igdb_id=i + 1,
        )
        db_session.add(tag)

    db_session.commit()

    # 全てのタグが作成されたことを確認
    for tag_class in classes:
        tag = db_session.query(GameTag).filter_by(tag_class=tag_class).first()
        assert tag is not None
        assert tag.tag_class == tag_class
