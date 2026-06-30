"""
database/models.py
==================
SQLite schema definitions and DDL for Nova Voice Assistant.

All schema creation is handled here.  The ``storage.py`` module
uses these constants when bootstrapping the database.

Tables
------
- users           — registered user profiles
- conversations   — full chat / voice history
- reminders       — scheduled reminder records
- settings        — key-value application settings
- command_history — log of executed commands
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DDL statements — executed in dependency order
# ---------------------------------------------------------------------------

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    wake_word   TEXT    NOT NULL DEFAULT 'nova',
    preferences TEXT    NOT NULL DEFAULT '{}',   -- JSON blob
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);
"""

CREATE_CONVERSATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 1,
    role       TEXT    NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content    TEXT    NOT NULL,
    intent     TEXT,                              -- detected intent label
    timestamp  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

CREATE_REMINDERS_TABLE = """
CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL DEFAULT 1,
    message      TEXT    NOT NULL,
    trigger_time TEXT    NOT NULL,               -- ISO-8601 datetime
    recurrence   TEXT             DEFAULT NULL,  -- 'daily' | 'weekly' | NULL
    active       INTEGER NOT NULL DEFAULT 1,     -- 0=dismissed, 1=active
    fired        INTEGER NOT NULL DEFAULT 0,     -- 0=pending, 1=fired
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);
"""

CREATE_COMMAND_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS command_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL DEFAULT 1,
    command    TEXT    NOT NULL,   -- raw user utterance
    intent     TEXT,               -- resolved intent
    result     TEXT,               -- plain-text result / response
    success    INTEGER NOT NULL DEFAULT 1,
    timestamp  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

# Indexes for common query patterns
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_conversations_timestamp ON conversations(timestamp DESC);",
    "CREATE INDEX IF NOT EXISTS idx_reminders_trigger_time ON reminders(trigger_time);",
    "CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders(active, fired);",
    "CREATE INDEX IF NOT EXISTS idx_command_history_user_id ON command_history(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_command_history_timestamp ON command_history(timestamp DESC);",
]

# All DDL statements in execution order
ALL_DDL: list[str] = [
    CREATE_USERS_TABLE,
    CREATE_CONVERSATIONS_TABLE,
    CREATE_REMINDERS_TABLE,
    CREATE_SETTINGS_TABLE,
    CREATE_COMMAND_HISTORY_TABLE,
    *CREATE_INDEXES,
]

# ---------------------------------------------------------------------------
# Data-class style dicts returned by storage queries (typed for clarity)
# ---------------------------------------------------------------------------

# These are plain TypedDicts — avoids pulling in a heavy ORM.
from typing import Optional, TypedDict


class UserRecord(TypedDict):
    id: int
    name: str
    wake_word: str
    preferences: str   # JSON string
    created_at: str
    updated_at: str


class ConversationRecord(TypedDict):
    id: int
    user_id: int
    role: str
    content: str
    intent: Optional[str]
    timestamp: str


class ReminderRecord(TypedDict):
    id: int
    user_id: int
    message: str
    trigger_time: str
    recurrence: Optional[str]
    active: int
    fired: int
    created_at: str


class SettingRecord(TypedDict):
    key: str
    value: str
    updated_at: str


class CommandHistoryRecord(TypedDict):
    id: int
    user_id: int
    command: str
    intent: Optional[str]
    result: Optional[str]
    success: int
    timestamp: str
