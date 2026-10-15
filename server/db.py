"""SQLite: схема и тонкая обёртка. Каждое изменение сразу коммитится (SPEC 3.4)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    name_key    TEXT NOT NULL UNIQUE,
    avatar_kind TEXT NOT NULL,
    avatar_ref  TEXT NOT NULL,
    is_host     INTEGER NOT NULL DEFAULT 0,
    in_scoring  INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    source    TEXT NOT NULL,
    ref       TEXT NOT NULL DEFAULT '',
    amount    INTEGER NOT NULL,
    note      TEXT NOT NULL DEFAULT '',
    ts        REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id       TEXT PRIMARY KEY,
    shown_at REAL
);
CREATE TABLE IF NOT EXISTS photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    author_id  INTEGER,
    path       TEXT NOT NULL,
    thumb      TEXT NOT NULL,
    hidden     INTEGER NOT NULL DEFAULT 0,
    deleted    INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS pumpkins (
    player_id  INTEGER PRIMARY KEY,
    version    INTEGER NOT NULL DEFAULT 0,
    data       TEXT NOT NULL DEFAULT '{}',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
    voter_id          INTEGER PRIMARY KEY,
    pumpkin_player_id INTEGER
);
CREATE TABLE IF NOT EXISTS event_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    player_id INTEGER,
    text      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_player ON ledger(player_id);
"""

# Таблицы, которые очищает «Сбросить вечер».
RESET_TABLES = ["players", "ledger", "facts", "photos", "pumpkins", "votes", "event_log", "settings"]


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    # --- settings (JSON-значения) ---
    def get_setting(self, key: str, default=None):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def all_settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.all("SELECT key, value FROM settings")}

    def backup_to(self, dest: Path) -> None:
        """Консистентная копия базы (sqlite backup API)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self.conn.backup(target)
            finally:
                target.close()

    def wipe(self) -> None:
        with self._lock:
            self.conn.execute("BEGIN")
            for t in RESET_TABLES:
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.execute("DELETE FROM sqlite_sequence")
            self.conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self.conn.close()
