"""Small SQLite store used to ignore duplicate Telegram webhook updates."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class UpdateStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=15) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_processed_at "
                "ON processed_updates(processed_at)"
            )
            connection.commit()

    def has_processed(self, update_id: int) -> bool:
        with sqlite3.connect(self.database_path, timeout=15) as connection:
            row = connection.execute(
                "SELECT 1 FROM processed_updates WHERE update_id = ? LIMIT 1",
                (update_id,),
            ).fetchone()
            return row is not None

    def mark_processed(self, update_id: int) -> None:
        now = int(time.time())
        cutoff = now - (7 * 24 * 60 * 60)
        with sqlite3.connect(self.database_path, timeout=15) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO processed_updates(update_id, processed_at) "
                "VALUES (?, ?)",
                (update_id, now),
            )
            connection.execute(
                "DELETE FROM processed_updates WHERE processed_at < ?", (cutoff,)
            )
            connection.commit()
