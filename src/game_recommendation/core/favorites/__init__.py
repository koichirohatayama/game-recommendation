"""ユーザーお気に入り向けローダー。"""

from game_recommendation.core.favorites.loader import FavoriteLoader, FavoriteLoaderError
from game_recommendation.core.favorites.query import FavoritesQuery, FavoritesQueryError

__all__ = [
    "FavoriteLoader",
    "FavoriteLoaderError",
    "FavoritesQuery",
    "FavoritesQueryError",
]
