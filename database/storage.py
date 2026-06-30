"""
database/storage.py
===================
Thread-safe SQLite CRUD layer for Nova Voice Assistant.

Design
------
- All connections are opened per-operation to avoid cross-thread issues.
- ``check_same_thread=False`` + WAL journal mode allows concurrent reads.
- A single ``DatabaseManager`` instance is created at startup (singleton).
- All public methods return typed records (dicts matching TypedDicts in models.py).

Usage
-----
    from database.storage import db
    db.add_conversation(user_id=1, role="user", content="Hello Nova")
    history = db.get_recent_conversations(user_id=1, limit=10)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from database.models import (
    ALL_DDL,
    CommandHistoryRecord,
    ConversationRecord,
    ReminderRecord,
    SettingRecord,
    UserRecord,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseManager:
    """
    Centralised SQLite data-access layer.

    Thread Safety
    -------------
    Uses a threading.Lock to serialise write operations.
    Reads are allowed concurrently thanks to WAL mode.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._write_lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a short-lived, auto-closing connection."""
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _bootstrap(self) -> None:
        """Create all tables and indexes if they do not yet exist."""
        with self._write_lock, self._connect() as conn:
            for ddl in ALL_DDL:
                conn.execute(ddl)
            # Insert default user if table is empty
            cursor = conn.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users (name, wake_word, preferences) VALUES (?, ?, ?)",
                    ("User", "nova", "{}"),
                )
        logger.debug("Database bootstrap complete: %s", self._db_path)

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def get_user(self, user_id: int = 1) -> Optional[UserRecord]:
        """Fetch a user by primary key."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None  # type: ignore[return-value]

    def get_all_users(self) -> List[UserRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
            return [dict(r) for r in rows]  # type: ignore[return-value]

    def create_user(self, name: str, wake_word: str = "nova") -> int:
        """Insert a new user and return its id."""
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO users (name, wake_word, preferences) VALUES (?, ?, ?)",
                (name, wake_word.lower(), "{}"),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def update_user_preferences(self, user_id: int, preferences: dict) -> None:
        """Merge new keys into the user's JSON preferences blob."""
        with self._write_lock, self._connect() as conn:
            row = conn.execute(
                "SELECT preferences FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is None:
                return
            existing = json.loads(row["preferences"] or "{}")
            existing.update(preferences)
            conn.execute(
                "UPDATE users SET preferences = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') WHERE id = ?",
                (json.dumps(existing), user_id),
            )

    def update_user_wake_word(self, user_id: int, wake_word: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE users SET wake_word = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') WHERE id = ?",
                (wake_word.lower(), user_id),
            )

    # ------------------------------------------------------------------
    # Conversation CRUD
    # ------------------------------------------------------------------

    def add_conversation(
        self,
        role: str,
        content: str,
        user_id: int = 1,
        intent: Optional[str] = None,
    ) -> int:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (user_id, role, content, intent) VALUES (?, ?, ?, ?)",
                (user_id, role, content, intent),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_recent_conversations(
        self,
        user_id: int = 1,
        limit: int = 50,
    ) -> List[ConversationRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]  # type: ignore[return-value]

    def clear_conversations(self, user_id: int = 1) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM conversations WHERE user_id = ?", (user_id,)
            )

    def get_conversation_context(
        self,
        user_id: int = 1,
        limit: int = 10,
    ) -> List[dict]:
        """
        Return the last N turns in OpenAI message format
        (list of {'role': ..., 'content': ...}).
        """
        rows = self.get_recent_conversations(user_id=user_id, limit=limit)
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    # ------------------------------------------------------------------
    # Reminder CRUD
    # ------------------------------------------------------------------

    def add_reminder(
        self,
        message: str,
        trigger_time: datetime,
        user_id: int = 1,
        recurrence: Optional[str] = None,
    ) -> int:
        with self._write_lock, self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reminders (user_id, message, trigger_time, recurrence)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, message, trigger_time.isoformat(timespec="seconds"), recurrence),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_pending_reminders(self) -> List[ReminderRecord]:
        """Return all active, unfired reminders whose trigger time has passed."""
        now_str = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE active = 1 AND fired = 0 AND trigger_time <= ?
                ORDER BY trigger_time
                """,
                (now_str,),
            ).fetchall()
            return [dict(r) for r in rows]  # type: ignore[return-value]

    def get_all_active_reminders(self, user_id: int = 1) -> List[ReminderRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM reminders
                WHERE user_id = ? AND active = 1
                ORDER BY trigger_time
                """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]  # type: ignore[return-value]

    def mark_reminder_fired(self, reminder_id: int, recurrence: Optional[str] = None) -> None:
        """
        Mark a reminder as fired.  If recurrence is set, reschedule it
        by advancing the trigger_time by the appropriate delta.
        """
        with self._write_lock, self._connect() as conn:
            if recurrence == "daily":
                conn.execute(
                    """
                    UPDATE reminders
                    SET fired = 0,
                        trigger_time = strftime('%Y-%m-%dT%H:%M:%S',
                            datetime(trigger_time, '+1 day'))
                    WHERE id = ?
                    """,
                    (reminder_id,),
                )
            elif recurrence == "weekly":
                conn.execute(
                    """
                    UPDATE reminders
                    SET fired = 0,
                        trigger_time = strftime('%Y-%m-%dT%H:%M:%S',
                            datetime(trigger_time, '+7 days'))
                    WHERE id = ?
                    """,
                    (reminder_id,),
                )
            else:
                conn.execute(
                    "UPDATE reminders SET fired = 1, active = 0 WHERE id = ?",
                    (reminder_id,),
                )

    def delete_reminder(self, reminder_id: int) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    # ------------------------------------------------------------------
    # Settings CRUD
    # ------------------------------------------------------------------

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')
                """,
                (key, value),
            )

    def get_all_settings(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # ------------------------------------------------------------------
    # Command History CRUD
    # ------------------------------------------------------------------

    def log_command(
        self,
        command: str,
        result: Optional[str] = None,
        intent: Optional[str] = None,
        success: bool = True,
        user_id: int = 1,
    ) -> None:
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO command_history (user_id, command, intent, result, success)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, command, intent, result, int(success)),
            )

    def get_command_history(
        self,
        user_id: int = 1,
        limit: int = 100,
    ) -> List[CommandHistoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM command_history
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Module-level singleton — import from here everywhere
# ---------------------------------------------------------------------------
_db_instance: Optional[DatabaseManager] = None


def init_database(db_path: Path) -> DatabaseManager:
    """Initialise the global DatabaseManager singleton."""
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager(db_path)
    return _db_instance


def get_db() -> DatabaseManager:
    """Return the already-initialised singleton; raises if not yet initialised."""
    if _db_instance is None:
        raise RuntimeError(
            "Database not initialised. Call init_database() from main.py first."
        )
    return _db_instance
