"""
commands/timer.py
=================
Timer command handler for Nova Voice Assistant.

Supports setting countdown timers with voice notification on completion.
Multiple concurrent timers are supported via threading.Timer.

Handler
-------
    handle(entities: dict) -> str
    entities keys: duration_minutes (int|float)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger
from utils.helpers import format_duration, extract_number

logger = get_logger(__name__)

# Global registry of active timers so they can be listed / cancelled
_active_timers: List[dict] = []
_timer_lock = threading.Lock()

# TTS callback injected at startup by the main orchestrator
_tts_callback: Optional[Callable[[str], None]] = None


def set_tts_callback(callback: Callable[[str], None]) -> None:
    """Inject the TTS speak function so timer alerts can be spoken."""
    global _tts_callback
    _tts_callback = callback


def _timer_fired(timer_id: int, message: str) -> None:
    """Called when a timer expires."""
    # Remove from active list
    with _timer_lock:
        global _active_timers
        _active_timers = [t for t in _active_timers if t["id"] != timer_id]

    logger.info("Timer %d fired: %s", timer_id, message)
    if _tts_callback:
        _tts_callback(message)
    else:
        print(f"\n🔔 TIMER: {message}\n")


def handle(entities: Dict[str, Any]) -> str:
    """
    Set a countdown timer.

    Parameters
    ----------
    entities:   Must contain 'duration_minutes' (int/float).
                May also contain 'duration_seconds' as alternative.

    Returns
    -------
    Confirmation string.
    """
    # Extract duration — try minutes first, then seconds
    duration_minutes: Optional[float] = None
    raw = entities.get("duration_minutes") or entities.get("duration")

    if raw is not None:
        try:
            duration_minutes = float(raw)
        except (ValueError, TypeError):
            duration_minutes = extract_number(str(raw))
    else:
        # Parse from raw_text if present
        raw_text = entities.get("raw_text", "")
        duration_minutes = extract_number(raw_text)

    if duration_minutes is None or duration_minutes <= 0:
        return "I couldn't determine the timer duration. Please say something like 'Set a timer for 5 minutes'."

    total_seconds = duration_minutes * 60
    human = format_duration(total_seconds)
    end_time = datetime.now() + timedelta(seconds=total_seconds)

    with _timer_lock:
        timer_id = len(_active_timers) + 1
        alert_message = f"Your {human} timer is up!"

        t = threading.Timer(
            interval=total_seconds,
            function=_timer_fired,
            args=(timer_id, alert_message),
        )
        t.daemon = True
        t.start()

        _active_timers.append({
            "id": timer_id,
            "duration": human,
            "end_time": end_time,
            "thread": t,
        })

    logger.info("Timer %d set for %s (ends at %s)", timer_id, human, end_time.strftime("%H:%M:%S"))
    return f"Timer set for {human}. I'll let you know when it's done."


def list_active_timers() -> str:
    """Return a human-readable list of active timers."""
    with _timer_lock:
        if not _active_timers:
            return "You have no active timers."
        descriptions = [
            f"Timer {t['id']}: {t['duration']} (ends at {t['end_time'].strftime('%H:%M:%S')})"
            for t in _active_timers
        ]
    return "Active timers: " + ", ".join(descriptions)


def cancel_all_timers() -> None:
    """Cancel all running timers (called on shutdown)."""
    with _timer_lock:
        for t_info in _active_timers:
            t_info["thread"].cancel()
        _active_timers.clear()
    logger.info("All timers cancelled")
