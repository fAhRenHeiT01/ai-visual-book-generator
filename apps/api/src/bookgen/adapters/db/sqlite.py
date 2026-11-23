"""SQLite session metadata and insert-once canonical selected page snapshots."""

from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from bookgen.schemas import BookContext, ImageAssetMeta, PageGenerationResult


class SQLiteSessionRepository:
    def __init__(self, path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Use a file-backed SQLite database for durable checkpoints")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, context TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_assets (
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                asset_id TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (session_id, asset_id)
            );
            CREATE TABLE IF NOT EXISTS page_snapshots (
                session_id TEXT NOT NULL REFERENCES sessions(session_id),
                page_id TEXT NOT NULL, page_number INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (session_id, page_id), UNIQUE (session_id, page_number)
            );
        """)

    def create_session(self, context=None):
        session_id = uuid4().hex
        context = context or BookContext()
        with self._lock, self._connection:
            self._connection.execute("INSERT INTO sessions VALUES (?, ?)", (session_id, context.model_dump_json()))
        return session_id

    def load_context(self, session_id):
        with self._lock:
            row = self._connection.execute("SELECT context FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return BookContext.model_validate_json(row[0])

    def save_assets(self, session_id, assets):
        self.load_context(session_id)
        with self._lock, self._connection:
            self._connection.executemany("INSERT INTO session_assets VALUES (?, ?, ?)",
                [(session_id, asset.asset_id, asset.model_dump_json()) for asset in assets])

    def load_assets(self, session_id):
        self.load_context(session_id)
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM session_assets WHERE session_id=? ORDER BY rowid", (session_id,)).fetchall()
        return [ImageAssetMeta.model_validate_json(row[0]) for row in rows]

    def save_snapshot(self, session_id, page):
        if page.selected_option_id not in ("option_a", "option_b"):
            raise ValueError("Only selected pages can be committed")
        with self._lock, self._connection:
            self._connection.execute("INSERT INTO page_snapshots VALUES (?, ?, ?, ?) ON CONFLICT(session_id, page_id) DO NOTHING",
                (session_id, page.page_id, page.page_number, page.model_dump_json()))
            existing = self._connection.execute("SELECT payload FROM page_snapshots WHERE session_id=? AND page_id=?", (session_id, page.page_id)).fetchone()
            if PageGenerationResult.model_validate_json(existing[0]) != page:
                raise ValueError("Page was already committed with another selection")

    def load_snapshots(self, session_id):
        self.load_context(session_id)
        with self._lock:
            rows = self._connection.execute("SELECT payload FROM page_snapshots WHERE session_id=? ORDER BY page_number", (session_id,)).fetchall()
        return [PageGenerationResult.model_validate_json(row[0]) for row in rows]

    def close(self):
        self._connection.close()
