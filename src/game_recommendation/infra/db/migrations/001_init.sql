PRAGMA foreign_keys = ON;

-- IGDB 由来のゲーム詳細
CREATE TABLE IF NOT EXISTS igdb_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    igdb_id INTEGER NOT NULL UNIQUE,
    slug TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags_cache TEXT NOT NULL DEFAULT '',
    release_date TEXT,
    cover_url TEXT,
    summary TEXT,
    checksum TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_igdb_games_release
    ON igdb_games (release_date);

-- タグのマスタテーブル
CREATE TABLE IF NOT EXISTS game_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- タグとゲームの中間テーブル
CREATE TABLE IF NOT EXISTS game_tag_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (game_id, tag_id),
    FOREIGN KEY (game_id) REFERENCES igdb_games(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES game_tags(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_game_tag_links_game_id
    ON game_tag_links (game_id);

-- 単一ユーザーの「お気に入り」ゲーム管理
CREATE TABLE IF NOT EXISTS user_favorite_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    notes TEXT,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (game_id),
    FOREIGN KEY (game_id) REFERENCES igdb_games(id) ON DELETE CASCADE
);

-- 埋め込みテーブル（既存）
CREATE TABLE IF NOT EXISTS game_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL UNIQUE,
    dimension INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_game_embeddings_game_id
    ON game_embeddings (game_id);

CREATE INDEX IF NOT EXISTS idx_game_embeddings_dimension
    ON game_embeddings (dimension);
