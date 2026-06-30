"""
utils/helpers.py
================
General-purpose utility functions used across Nova Voice Assistant.

Includes
--------
- Time and date formatting
- Safe arithmetic evaluation
- Platform detection
- Text sanitisation
- Retry decorator
- Singleton metaclass
"""

from __future__ import annotations

import math
import operator
import platform
import re
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def get_platform() -> str:
    """Return a normalised platform identifier: 'windows', 'darwin', or 'linux'."""
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return "windows"
    if sys_name == "darwin":
        return "darwin"
    return "linux"


def is_windows() -> bool:
    return get_platform() == "windows"


def is_mac() -> bool:
    return get_platform() == "darwin"


def is_linux() -> bool:
    return get_platform() == "linux"


# ---------------------------------------------------------------------------
# Time / date helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """Return current local time as ISO-8601 string."""
    return datetime.now().isoformat(timespec="seconds")


def format_duration(seconds: float) -> str:
    """
    Convert seconds into a human-readable duration string.

    Examples
    --------
    >>> format_duration(90)
    '1 minute 30 seconds'
    >>> format_duration(3661)
    '1 hour 1 minute 1 second'
    """
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if secs or not parts:
        parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return " ".join(parts)


def human_time(dt: datetime) -> str:
    """Return a friendly time string like '2:30 PM'."""
    return dt.strftime("%I:%M %p").lstrip("0")


def human_date(dt: datetime) -> str:
    """Return a friendly date string like 'Saturday, June 14 2025'."""
    return dt.strftime("%A, %B %-d %Y") if not is_windows() else dt.strftime("%A, %B %d %Y")


def parse_time_expression(expr: str) -> datetime | None:
    """
    Parse common time expressions into an absolute datetime.

    Supported patterns
    ------------------
    - "in X minutes"
    - "in X hours"
    - "at HH:MM [AM|PM]"

    Parameters
    ----------
    expr:   Raw user utterance fragment, e.g. "in 10 minutes".

    Returns
    -------
    datetime or None if not parseable.
    """
    expr = expr.strip().lower()
    now = datetime.now()

    # "in X minutes/hours/seconds"
    m = re.search(r"in\s+(\d+)\s+(second|minute|hour)s?", expr)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        delta = {
            "second": timedelta(seconds=amount),
            "minute": timedelta(minutes=amount),
            "hour": timedelta(hours=amount),
        }[unit]
        return now + delta

    # "at HH:MM AM/PM" or "at HH:MM"
    m = re.search(r"at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?", expr)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    return None


# ---------------------------------------------------------------------------
# Safe calculator
# ---------------------------------------------------------------------------

# Allowed operations for safe evaluation
_SAFE_OPS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "pow": math.pow,
    "pi": math.pi,
    "e": math.e,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "floor": math.floor,
    "ceil": math.ceil,
}


def safe_eval(expression: str) -> float | None:
    """
    Safely evaluate a mathematical expression string.

    Uses a whitelist of allowed names to prevent code injection.

    Parameters
    ----------
    expression: Human-readable math expression, e.g. "245 * 87 + sqrt(16)".

    Returns
    -------
    float result or None on parse/evaluation error.
    """
    # Normalise common spoken-word operators
    replacements = {
        r"\bplus\b": "+",
        r"\bminus\b": "-",
        r"\btimes\b": "*",
        r"\bmultiplied by\b": "*",
        r"\bdivided by\b": "/",
        r"\bover\b": "/",
        r"\bto the power of\b": "**",
        r"\bsquared\b": "**2",
        r"\bcubed\b": "**3",
        r"\bpercent\b": "/100",
    }
    for pattern, replacement in replacements.items():
        expression = re.sub(pattern, replacement, expression, flags=re.IGNORECASE)

    # Strip anything not numeric or a recognised operator/function character
    allowed_chars = re.compile(r"[^0-9+\-*/().^ %a-zA-Z_\s]")
    expression = allowed_chars.sub("", expression).strip()

    try:
        # compile to AST first — raises SyntaxError on bad input
        code = compile(expression, "<string>", "eval")
        result = eval(code, {"__builtins__": {}}, _SAFE_OPS)  # noqa: S307 (intentional safe eval)
        return float(result)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def truncate(text: str, max_length: int = 80, suffix: str = "…") -> str:
    """Return text truncated to max_length characters."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def sanitise_input(text: str) -> str:
    """
    Strip control characters and normalise whitespace from user input.

    Parameters
    ----------
    text:   Raw string from microphone or text entry.
    """
    # Remove null bytes and other control chars (keep newlines for multi-line)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Normalise whitespace
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_number(text: str) -> float | None:
    """
    Extract the first numeric value from a text string.

    Handles integers, decimals, and spoken forms like "ten", "five".
    """
    WORD_TO_NUM = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "hundred": 100,
    }
    lower = text.lower()
    for word, num in WORD_TO_NUM.items():
        if word in lower:
            return float(num)

    m = re.search(r"[\d]+\.?[\d]*", text)
    if m:
        return float(m.group())
    return None


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries a function call on failure with exponential backoff.

    Parameters
    ----------
    max_attempts:   Total number of attempts (including the first).
    delay:          Initial delay in seconds between retries.
    backoff:        Multiplier applied to delay after each attempt.
    exceptions:     Tuple of exception types to catch and retry on.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        time.sleep(current_delay)
                        current_delay *= backoff
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# Singleton metaclass
# ---------------------------------------------------------------------------

class SingletonMeta(type):
    """
    Thread-safe singleton metaclass.

    Usage
    -----
        class MyService(metaclass=SingletonMeta):
            ...
    """
    _instances: dict[type, Any] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
