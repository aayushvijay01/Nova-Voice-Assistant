"""
assistant/tts.py
================
Text-to-Speech engine for Nova Voice Assistant.

Uses pyttsx3 (100% offline, cross-platform) with a thread-safe speech queue.
Supports adjustable rate, volume, voice selection, and interruption.

Usage
-----
    from assistant.tts import TTSEngine
    tts = TTSEngine()
    tts.speak("Hello, I am Nova.")
    tts.stop()
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

import pyttsx3

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

_STOP_SENTINEL = "__STOP__"
_FLUSH_SENTINEL = "__FLUSH__"


class TTSEngine:
    """
    Thread-safe, queue-based text-to-speech wrapper around pyttsx3.

    The engine runs a dedicated background thread that drains the speech
    queue, so callers never block.  An internal event signals when speaking
    is in progress so it can be interrupted.
    """

    def __init__(
        self,
        rate: int = settings.tts_rate,
        volume: float = settings.tts_volume,
        voice_index: int = settings.tts_voice_index,
        on_start: Optional[Callable[[str], None]] = None,
        on_end: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Parameters
        ----------
        rate:           Words per minute (50–400).
        volume:         0.0–1.0.
        voice_index:    Index into pyttsx3's voice list.
        on_start:       Callback invoked when speech begins (receives text).
        on_end:         Callback invoked when speech finishes.
        """
        self._rate = rate
        self._volume = volume
        self._voice_index = voice_index
        self._on_start = on_start
        self._on_end = on_end

        self._queue: queue.Queue[str] = queue.Queue(maxsize=settings.tts_queue_maxsize)
        self._speaking = threading.Event()
        self._stop_event = threading.Event()
        self._engine: Optional[pyttsx3.Engine] = None
        self._available_voices: list[str] = []

        self._thread = threading.Thread(
            target=self._worker,
            name="TTSWorker",
            daemon=True,
        )
        self._thread.start()
        logger.info("TTS engine started (rate=%d wpm, volume=%.1f)", rate, volume)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str, priority: bool = False) -> None:
        """
        Enqueue text for speech.

        Parameters
        ----------
        text:       The sentence or phrase to speak.
        priority:   If True, clears the queue before enqueuing (interrupts current).
        """
        if not text or not text.strip():
            return
        if priority:
            self.flush()
        try:
            self._queue.put_nowait(text.strip())
        except queue.Full:
            logger.warning("TTS queue full — dropping utterance: %s", text[:40])

    def stop(self) -> None:
        """Immediately stop any current speech and clear the queue."""
        self.flush()
        if self._engine and self._speaking.is_set():
            try:
                self._engine.stop()
            except RuntimeError:
                pass

    def flush(self) -> None:
        """Drain the pending speech queue without stopping the current utterance."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    def is_speaking(self) -> bool:
        """Return True if the engine is currently synthesising speech."""
        return self._speaking.is_set()

    def set_rate(self, rate: int) -> None:
        """Update the speech rate (words per minute)."""
        self._rate = max(50, min(400, rate))
        logger.debug("TTS rate set to %d", self._rate)

    def set_volume(self, volume: float) -> None:
        """Update the volume (0.0 – 1.0)."""
        self._volume = max(0.0, min(1.0, volume))

    def set_voice(self, index: int) -> None:
        """Switch to the pyttsx3 voice at the given index."""
        if index < len(self._available_voices):
            self._voice_index = index
            logger.debug("TTS voice set to index %d", index)

    def get_available_voices(self) -> list[str]:
        """Return the display names of all available system voices."""
        return list(self._available_voices)

    def shutdown(self) -> None:
        """Gracefully stop the background worker thread."""
        self._stop_event.set()
        try:
            self._queue.put_nowait(_STOP_SENTINEL)
        except queue.Full:
            pass
        self._thread.join(timeout=5)
        logger.info("TTS engine shut down")

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _init_engine(self) -> pyttsx3.Engine:
        """Initialise pyttsx3 engine (must be called from the worker thread)."""
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        self._available_voices = [v.name for v in voices] if voices else []

        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)

        if voices and self._voice_index < len(voices):
            engine.setProperty("voice", voices[self._voice_index].id)

        return engine

    def _worker(self) -> None:
        """Background thread: drain the queue and synthesise speech."""
        try:
            self._engine = self._init_engine()
        except Exception as exc:
            logger.error("Failed to initialise pyttsx3: %s", exc)
            return

        while not self._stop_event.is_set():
            try:
                text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if text == _STOP_SENTINEL:
                self._queue.task_done()
                break

            # Apply any pending property changes
            self._engine.setProperty("rate", self._rate)
            self._engine.setProperty("volume", self._volume)
            voices = self._engine.getProperty("voices")
            if voices and self._voice_index < len(voices):
                self._engine.setProperty("voice", voices[self._voice_index].id)

            self._speaking.set()
            if self._on_start:
                try:
                    self._on_start(text)
                except Exception:
                    pass

            logger.debug("TTS speaking: %s", text[:60])
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:
                logger.error("TTS error: %s", exc)
            finally:
                self._speaking.clear()
                self._queue.task_done()
                if self._on_end:
                    try:
                        self._on_end()
                    except Exception:
                        pass
