"""
commands/reminder.py
====================
Reminder command handler for Nova Voice Assistant.

Creates reminders stored in SQLite and fired by the background scheduler.
Supports one-time and recurring (daily/weekly) reminders.

Handler
-------
    handle(entities: dict) -> str
    entities keys: message (str), time (str|None), recurrence (str|None)

Scheduler
---------
    ReminderScheduler — runs in a daemon thread, polls every 30 seconds.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger
from utils.helpers import parse_time_expression

logger = get_logger(__name__)

# Injected at startup by main.py
_tts_callback: Optional[Callable[[str], None]] = None
_db_get = None  # Callable that returns DatabaseManager


def set_tts_callback(callback: Callable[[str], None]) -> None:
    global _tts_callback
    _tts_callback = callback


def set_db_getter(getter: Callable) -> None:
    global _db_get
    _db_get = getter


def handle(entities: Dict[str, Any]) -> str:
    """
    Create a new reminder.

    Parameters
    ----------
    entities:
        message     — What to remind the user about.
        time        — ISO-8601 string or spoken time expression (optional).
        recurrence  — 'daily' | 'weekly' | None.

    Returns
    -------
    Confirmation string.
    """
    if _db_get is None:
        return "Reminder system is not initialised."

    db = _db_get()
    message: str = entities.get("message", "")
    time_str: Optional[str] = entities.get("time")
    recurrence: Optional[str] = entities.get("recurrence")
    raw_text: str = entities.get("raw_text", message)

    # Derive a clean message from the raw text
    if not message or message == raw_text:
        # Strip the trigger phrase to get just the reminder body
        import re
        message = re.sub(
            r"(?i)remind\s+me\s+(to\s+)?", "", raw_text
        ).strip()
        # Further strip "at X time" suffix for the label
        message = re.sub(r"\s+at\s+\d{1,2}[:.]?\d{0,2}\s*(am|pm)?$", "", message, flags=re.I).strip()
        if not message:
            message = raw_text

    # Parse trigger time
    trigger_dt: Optional[datetime] = None
    if time_str:
        try:
            trigger_dt = datetime.fromisoformat(time_str)
        except (ValueError, TypeError):
            trigger_dt = parse_time_expression(time_str)

    if trigger_dt is None:
        # Try extracting from raw utterance
        trigger_dt = parse_time_expression(raw_text)

    if trigger_dt is None:
        return (
            "I didn't catch when you want to be reminded. "
            "Please say something like 'Remind me to call John in 30 minutes' or 'at 6 PM'."
        )

    try:
        reminder_id = db.add_reminder(
            message=message,
            trigger_time=trigger_dt,
            recurrence=recurrence,
        )
        time_str_formatted = trigger_dt.strftime("%I:%M %p on %B %d")
        logger.info("Reminder %d set: %r at %s", reminder_id, message, trigger_dt)
        recur_suffix = f" This will repeat {recurrence}." if recurrence else ""
        return f"Got it! I'll remind you to {message} at {time_str_formatted}.{recur_suffix}"
    except Exception as exc:
        logger.error("Failed to save reminder: %s", exc)
        return "I had trouble saving your reminder. Please try again."


def list_reminders() -> str:
    """Return a spoken list of active reminders."""
    if _db_get is None:
        return "Reminder system is not initialised."
    db = _db_get()
    reminders = db.get_all_active_reminders()
    if not reminders:
        return "You have no active reminders."
    lines = [f"You have {len(reminders)} active reminder{'s' if len(reminders) > 1 else ''}."]
    for r in reminders:
        try:
            dt = datetime.fromisoformat(r["trigger_time"])
            lines.append(f"Reminder: {r['message']} at {dt.strftime('%I:%M %p')}.")
        except Exception:
            lines.append(f"Reminder: {r['message']}.")
    return " ".join(lines)


# ---------------------------------------------------------------------------
# Background Scheduler
# ---------------------------------------------------------------------------

class ReminderScheduler:
    """
    Daemon thread that polls the database every 30 seconds for due reminders
    and fires TTS notifications.
    """

    POLL_INTERVAL = 30  # seconds

    def __init__(self, db_getter: Callable, tts_callback: Callable[[str], None]) -> None:
        self._db_getter = db_getter
        self._tts_callback = tts_callback
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="ReminderScheduler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        logger.info("ReminderScheduler started (poll interval=%ds)", self.POLL_INTERVAL)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)
        logger.info("ReminderScheduler stopped")

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=self.POLL_INTERVAL):
            try:
                self._check_reminders()
            except Exception as exc:
                logger.error("ReminderScheduler error: %s", exc)

    def _check_reminders(self) -> None:
        db = self._db_getter()
        pending = db.get_pending_reminders()
        for reminder in pending:
            message = f"Reminder: {reminder['message']}"
            logger.info("Firing reminder %d: %r", reminder["id"], reminder["message"])
            try:
                self._tts_callback(message)
            except Exception as exc:
                logger.error("Failed to speak reminder: %s", exc)
            db.mark_reminder_fired(
                reminder_id=reminder["id"],
                recurrence=reminder.get("recurrence"),
            )
