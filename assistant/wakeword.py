"""
assistant/wakeword.py
=====================
Wake word detector for Nova Voice Assistant.

Performs keyword spotting by checking whether the transcribed text from a
short audio chunk contains the configured wake word (default: "nova").

The detector is intentionally lightweight:
- No extra ML model required (uses transcription from Whisper/SR)
- Toggle on/off at runtime
- Configurable sensitivity (fuzzy matching)
- Supports multiple aliases

Usage
-----
    from assistant.wakeword import WakeWordDetector
    detector = WakeWordDetector(wake_word="nova")
    if detector.is_wake_word("Hey Nova, what's the weather?"):
        ...
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Common phonetically-similar mishearings that STT models produce for "Nova"
_DEFAULT_ALIASES: list[str] = [
    "nova", "neva", "novah", "noa", "noah",
    "hey nova", "ok nova", "okay nova",
]


class WakeWordDetector:
    """
    Lightweight keyword-based wake word detector.

    Sensitivity controls fuzzy matching behaviour:
    - 0.0 — exact substring match only
    - 1.0 — very loose pattern matching
    """

    def __init__(
        self,
        wake_word: str = settings.wake_word,
        aliases: Optional[List[str]] = None,
        sensitivity: float = settings.wake_word_sensitivity,
        enabled: bool = settings.wake_word_enabled,
        on_detected: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Parameters
        ----------
        wake_word:      Primary trigger keyword.
        aliases:        Additional phonetic variants.
        sensitivity:    Matching threshold (0.0=strict, 1.0=loose).
        enabled:        Whether wake word detection is active.
        on_detected:    Callback invoked with the matched text when detected.
        """
        self._wake_word = wake_word.strip().lower()
        self._sensitivity = max(0.0, min(1.0, sensitivity))
        self._enabled = enabled
        self._on_detected = on_detected

        # Build keyword set from primary + aliases
        base_aliases = aliases if aliases is not None else _DEFAULT_ALIASES
        self._keywords: set[str] = {self._wake_word} | {
            a.strip().lower() for a in base_aliases
        }

        # Pre-compile pattern for efficiency
        self._pattern = self._build_pattern()
        logger.info(
            "WakeWordDetector initialised — keyword=%r  aliases=%d  sensitivity=%.2f",
            self._wake_word,
            len(self._keywords),
            self._sensitivity,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_wake_word(self, text: str) -> bool:
        """
        Return True if *text* contains the wake word or a recognised alias.

        Parameters
        ----------
        text:   Transcribed utterance to scan.
        """
        if not self._enabled or not text:
            return False

        normalised = text.strip().lower()

        # Fast exact / substring match
        if self._pattern.search(normalised):
            logger.debug("Wake word detected (exact): %r", normalised[:60])
            if self._on_detected:
                try:
                    self._on_detected(normalised)
                except Exception:
                    pass
            return True

        # Fuzzy match at higher sensitivity
        if self._sensitivity >= 0.5:
            if self._fuzzy_match(normalised):
                logger.debug("Wake word detected (fuzzy): %r", normalised[:60])
                if self._on_detected:
                    try:
                        self._on_detected(normalised)
                    except Exception:
                        pass
                return True

        return False

    def strip_wake_word(self, text: str) -> str:
        """
        Remove the wake word prefix from an utterance.

        Example
        -------
        >>> strip_wake_word("Hey Nova, what's the weather?")
        "what's the weather?"
        """
        normalised = text.strip()
        cleaned = self._pattern.sub("", normalised, count=1).strip()
        # Remove leading punctuation / conjunctions left after strip
        cleaned = re.sub(r"^[,\.\!\?\s]+", "", cleaned).strip()
        return cleaned or normalised

    def enable(self) -> None:
        """Enable wake word detection."""
        self._enabled = True
        logger.info("Wake word detection enabled")

    def disable(self) -> None:
        """Disable wake word detection (listen to everything)."""
        self._enabled = False
        logger.info("Wake word detection disabled")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_wake_word(self, word: str) -> None:
        """Update the primary wake word at runtime."""
        self._wake_word = word.strip().lower()
        self._keywords = {self._wake_word} | (self._keywords - {next(iter(self._keywords))})
        self._pattern = self._build_pattern()
        logger.info("Wake word updated to %r", self._wake_word)

    def set_sensitivity(self, sensitivity: float) -> None:
        self._sensitivity = max(0.0, min(1.0, sensitivity))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_pattern(self) -> re.Pattern:
        """
        Build a compiled regex that matches any keyword as a word boundary.
        Sorts by length desc so longer phrases match first.
        """
        escaped = sorted(
            (re.escape(kw) for kw in self._keywords),
            key=len,
            reverse=True,
        )
        pattern_str = r"\b(?:" + "|".join(escaped) + r")\b"
        return re.compile(pattern_str, re.IGNORECASE)

    def _fuzzy_match(self, text: str) -> bool:
        """
        Fuzzy matching: check for character-level similarity to the wake word.
        Useful for STT output like "nova" → "noba", "nova" → "novaa".
        """
        words = text.split()
        threshold = max(1, int(len(self._wake_word) * (1 - self._sensitivity)))
        for word in words:
            if abs(len(word) - len(self._wake_word)) <= threshold:
                mismatches = sum(
                    a != b for a, b in zip(word, self._wake_word)
                )
                if mismatches <= threshold:
                    return True
        return False
