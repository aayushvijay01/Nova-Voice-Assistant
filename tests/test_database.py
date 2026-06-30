"""
tests/test_database.py
======================
Unit tests for the SQLite database layer.

Uses an in-memory SQLite database so tests are isolated and fast.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path

from database.storage import DatabaseManager


def _make_db() -> DatabaseManager:
    """Create an in-memory database for testing."""
    return DatabaseManager(db_path=Path(":memory:"))


class TestDatabaseBootstrap(unittest.TestCase):

    def test_bootstrap_creates_default_user(self):
        db = _make_db()
        user = db.get_user(1)
        self.assertIsNotNone(user)
        self.assertEqual(user["name"], "User")
        self.assertEqual(user["wake_word"], "nova")


class TestUserCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_create_user(self):
        uid = self.db.create_user("Alice", wake_word="hey nova")
        self.assertGreater(uid, 0)
        user = self.db.get_user(uid)
        self.assertEqual(user["name"], "Alice")
        self.assertEqual(user["wake_word"], "hey nova")

    def test_get_all_users(self):
        self.db.create_user("Bob")
        self.db.create_user("Carol")
        users = self.db.get_all_users()
        self.assertGreaterEqual(len(users), 3)  # default + 2

    def test_update_preferences(self):
        self.db.update_user_preferences(1, {"theme": "dark", "city": "London"})
        user = self.db.get_user(1)
        import json
        prefs = json.loads(user["preferences"])
        self.assertEqual(prefs["theme"], "dark")
        self.assertEqual(prefs["city"], "London")

    def test_update_preferences_merges(self):
        self.db.update_user_preferences(1, {"key1": "val1"})
        self.db.update_user_preferences(1, {"key2": "val2"})
        user = self.db.get_user(1)
        import json
        prefs = json.loads(user["preferences"])
        self.assertIn("key1", prefs)
        self.assertIn("key2", prefs)

    def test_update_wake_word(self):
        self.db.update_user_wake_word(1, "jarvis")
        user = self.db.get_user(1)
        self.assertEqual(user["wake_word"], "jarvis")

    def test_get_nonexistent_user(self):
        user = self.db.get_user(9999)
        self.assertIsNone(user)


class TestConversationCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_add_and_retrieve_conversation(self):
        self.db.add_conversation(role="user", content="Hello Nova")
        self.db.add_conversation(role="assistant", content="Hello! How can I help?")
        history = self.db.get_recent_conversations(limit=10)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

    def test_conversation_limit(self):
        for i in range(20):
            self.db.add_conversation(role="user", content=f"Message {i}")
        history = self.db.get_recent_conversations(limit=5)
        self.assertEqual(len(history), 5)

    def test_conversation_context_format(self):
        self.db.add_conversation(role="user", content="Hi")
        self.db.add_conversation(role="assistant", content="Hello!")
        context = self.db.get_conversation_context(limit=5)
        self.assertEqual(len(context), 2)
        self.assertIn("role", context[0])
        self.assertIn("content", context[0])

    def test_clear_conversations(self):
        self.db.add_conversation(role="user", content="Test")
        self.db.clear_conversations()
        history = self.db.get_recent_conversations()
        self.assertEqual(len(history), 0)


class TestReminderCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_add_reminder(self):
        future = datetime.now() + timedelta(minutes=30)
        rid = self.db.add_reminder(message="Call John", trigger_time=future)
        self.assertGreater(rid, 0)

    def test_get_active_reminders(self):
        future = datetime.now() + timedelta(hours=1)
        self.db.add_reminder(message="Take medication", trigger_time=future)
        active = self.db.get_all_active_reminders()
        self.assertGreaterEqual(len(active), 1)

    def test_pending_reminders_past_trigger(self):
        past = datetime.now() - timedelta(minutes=1)
        self.db.add_reminder(message="Past reminder", trigger_time=past)
        pending = self.db.get_pending_reminders()
        self.assertGreaterEqual(len(pending), 1)
        self.assertEqual(pending[0]["message"], "Past reminder")

    def test_future_reminder_not_pending(self):
        future = datetime.now() + timedelta(hours=1)
        self.db.add_reminder(message="Future reminder", trigger_time=future)
        pending = self.db.get_pending_reminders()
        # Future reminders should not appear in pending
        messages = [r["message"] for r in pending]
        self.assertNotIn("Future reminder", messages)

    def test_mark_reminder_fired(self):
        past = datetime.now() - timedelta(seconds=1)
        rid = self.db.add_reminder(message="Test fire", trigger_time=past)
        self.db.mark_reminder_fired(rid)
        active = self.db.get_all_active_reminders()
        ids = [r["id"] for r in active]
        self.assertNotIn(rid, ids)

    def test_delete_reminder(self):
        future = datetime.now() + timedelta(hours=1)
        rid = self.db.add_reminder(message="To delete", trigger_time=future)
        self.db.delete_reminder(rid)
        active = self.db.get_all_active_reminders()
        ids = [r["id"] for r in active]
        self.assertNotIn(rid, ids)


class TestSettingsCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_set_and_get_setting(self):
        self.db.set_setting("theme", "dark")
        val = self.db.get_setting("theme")
        self.assertEqual(val, "dark")

    def test_get_missing_setting_with_default(self):
        val = self.db.get_setting("nonexistent_key", "default_val")
        self.assertEqual(val, "default_val")

    def test_update_existing_setting(self):
        self.db.set_setting("key", "first")
        self.db.set_setting("key", "second")
        val = self.db.get_setting("key")
        self.assertEqual(val, "second")

    def test_get_all_settings(self):
        self.db.set_setting("a", "1")
        self.db.set_setting("b", "2")
        all_settings = self.db.get_all_settings()
        self.assertIn("a", all_settings)
        self.assertIn("b", all_settings)


class TestCommandHistoryCRUD(unittest.TestCase):

    def setUp(self):
        self.db = _make_db()

    def test_log_command(self):
        self.db.log_command(
            command="What's the weather?",
            result="It's sunny and 25 degrees.",
            intent="get_weather",
            success=True,
        )
        history = self.db.get_command_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["intent"], "get_weather")

    def test_log_failed_command(self):
        self.db.log_command(command="bad input", success=False)
        history = self.db.get_command_history()
        self.assertEqual(history[0]["success"], 0)

    def test_history_limit(self):
        for i in range(20):
            self.db.log_command(command=f"cmd {i}")
        history = self.db.get_command_history(limit=5)
        self.assertEqual(len(history), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
