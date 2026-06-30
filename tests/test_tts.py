"""
tests/test_tts.py
=================
Unit tests for the TTS engine (mocked pyttsx3).
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch, call


class TestTTSEngine(unittest.TestCase):

    def setUp(self):
        """Mock pyttsx3 before importing TTSEngine."""
        self._pyttsx3_patch = patch("assistant.tts.pyttsx3")
        self._mock_pyttsx3 = self._pyttsx3_patch.start()

        # Setup mock engine
        self._mock_engine = MagicMock()
        self._mock_pyttsx3.init.return_value = self._mock_engine

        # Mock voice list
        voice = MagicMock()
        voice.name = "Test Voice"
        voice.id = "test-voice-id"
        self._mock_engine.getProperty.return_value = [voice]

        from assistant.tts import TTSEngine
        self.tts = TTSEngine(rate=150, volume=0.8, voice_index=0)
        # Brief wait for worker thread to initialise
        time.sleep(0.1)

    def tearDown(self):
        self.tts.shutdown()
        time.sleep(0.2)
        self._pyttsx3_patch.stop()

    def test_engine_initialises(self):
        self._mock_pyttsx3.init.assert_called_once()

    def test_speak_enqueues(self):
        self.tts.speak("Hello world")
        time.sleep(0.3)
        self._mock_engine.say.assert_called()

    def test_speak_empty_string_ignored(self):
        self.tts.speak("")
        self.tts.speak("   ")
        time.sleep(0.1)
        # Empty strings should not cause any TTS calls
        # (the worker only processes non-empty)
        self.assertEqual(self.tts._queue.qsize(), 0)

    def test_set_rate(self):
        self.tts.set_rate(200)
        self.assertEqual(self.tts._rate, 200)

    def test_set_rate_clamped(self):
        self.tts.set_rate(999)
        self.assertEqual(self.tts._rate, 400)
        self.tts.set_rate(-10)
        self.assertEqual(self.tts._rate, 50)

    def test_set_volume(self):
        self.tts.set_volume(0.5)
        self.assertEqual(self.tts._volume, 0.5)

    def test_set_volume_clamped(self):
        self.tts.set_volume(1.5)
        self.assertEqual(self.tts._volume, 1.0)
        self.tts.set_volume(-0.1)
        self.assertEqual(self.tts._volume, 0.0)

    def test_get_available_voices(self):
        voices = self.tts.get_available_voices()
        self.assertIsInstance(voices, list)
        self.assertEqual(voices[0], "Test Voice")

    def test_flush_clears_queue(self):
        for i in range(5):
            try:
                self.tts._queue.put_nowait(f"message {i}")
            except Exception:
                pass
        self.tts.flush()
        self.assertEqual(self.tts._queue.qsize(), 0)

    def test_on_start_callback(self):
        callback = MagicMock()
        self.tts._on_start = callback
        self.tts.speak("Testing callback")
        time.sleep(0.5)
        callback.assert_called_once_with("Testing callback")

    def test_on_end_callback(self):
        callback = MagicMock()
        self.tts._on_end = callback
        self.tts.speak("End callback test")
        time.sleep(0.5)
        callback.assert_called()


class TestTTSEngineShutdown(unittest.TestCase):

    def test_shutdown_stops_thread(self):
        with patch("assistant.tts.pyttsx3") as mock_pyttsx3:
            mock_engine = MagicMock()
            mock_pyttsx3.init.return_value = mock_engine
            voice = MagicMock()
            voice.name = "Voice"
            voice.id = "vid"
            mock_engine.getProperty.return_value = [voice]

            from assistant.tts import TTSEngine
            tts = TTSEngine()
            time.sleep(0.1)
            tts.shutdown()
            # Thread should be dead after shutdown
            tts._thread.join(timeout=3)
            self.assertFalse(tts._thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
