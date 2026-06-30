"""
tests/test_intent_engine.py
============================
Unit tests for the IntentEngine — both regex fallback and mocked OpenAI path.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestIntentEngineRegex(unittest.TestCase):
    """Test the offline regex-based intent extraction."""

    def _get_engine(self):
        """Get an IntentEngine with OpenAI disabled."""
        with patch("assistant.intent_engine.settings") as mock_settings:
            mock_settings.openai_available = False
            mock_settings.wake_word = "nova"
            mock_settings.default_city = "New York"
            from assistant.intent_engine import IntentEngine
            engine = IntentEngine()
        engine._openai_client = None  # force regex mode
        return engine

    def test_weather_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("What's the weather today?")
        self.assertEqual(result.intent, "get_weather")
        self.assertEqual(result.source, "regex")

    def test_weather_with_city(self):
        engine = self._get_engine()
        result = engine._extract_regex("What's the weather in London?")
        self.assertEqual(result.intent, "get_weather")
        self.assertIn("city", result.entities)

    def test_news_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Tell me today's top headlines")
        self.assertEqual(result.intent, "get_news")

    def test_timer_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Set a timer for 5 minutes")
        self.assertEqual(result.intent, "set_timer")
        self.assertIn("duration_minutes", result.entities)

    def test_reminder_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Remind me to call John at 6 PM")
        self.assertEqual(result.intent, "set_reminder")

    def test_time_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("What time is it?")
        self.assertEqual(result.intent, "get_time")

    def test_date_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("What's the date today?")
        self.assertEqual(result.intent, "get_date")

    def test_open_app_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Open Chrome")
        self.assertEqual(result.intent, "open_application")
        self.assertIn("app_name", result.entities)

    def test_web_search_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Search Google for Python tutorials")
        self.assertEqual(result.intent, "web_search")

    def test_calculator_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("What is 12 + 8?")
        self.assertEqual(result.intent, "calculate")

    def test_stop_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Stop")
        self.assertEqual(result.intent, "stop_listening")

    def test_system_shutdown_intent(self):
        engine = self._get_engine()
        result = engine._extract_regex("Shutdown the computer")
        self.assertEqual(result.intent, "system_control")

    def test_unknown_defaults_to_chitchat(self):
        engine = self._get_engine()
        result = engine._extract_regex("Blah blah completely random text")
        self.assertEqual(result.intent, "chitchat")

    def test_empty_text(self):
        engine = self._get_engine()
        result = engine.extract("")
        self.assertEqual(result.intent, "unknown")


class TestIntentEngineOpenAI(unittest.TestCase):
    """Test the OpenAI path with a mocked client."""

    def _get_engine_with_mock(self, mock_response: dict):
        """Return an IntentEngine wired to a mock OpenAI client."""
        with patch("assistant.intent_engine.settings") as mock_settings:
            mock_settings.openai_available = True
            mock_settings.openai_api_key = "sk-fake"
            mock_settings.openai_model = "gpt-4o-mini"
            mock_settings.openai_timeout = 10
            mock_settings.wake_word = "nova"
            mock_settings.default_city = "New York"
            mock_settings.wake_word_sensitivity = 0.5

            with patch("assistant.intent_engine.IntentEngine.__init__", return_value=None):
                from assistant.intent_engine import IntentEngine
                engine = IntentEngine.__new__(IntentEngine)
                engine._regex_rules = []  # skip rule build
                engine._openai_client = MagicMock()

        # Configure mock response
        import json
        tool_call = MagicMock()
        tool_call.function.arguments = json.dumps(mock_response)
        choice = MagicMock()
        choice.message.tool_calls = [tool_call]
        engine._openai_client.chat.completions.create.return_value.choices = [choice]

        return engine

    def test_openai_weather_intent(self):
        engine = self._get_engine_with_mock({
            "intent": "get_weather",
            "entities": {"city": "Paris"},
            "confidence": 0.95,
        })
        result = engine._extract_openai("What's the weather in Paris?", [])
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "get_weather")
        self.assertEqual(result.entities["city"], "Paris")
        self.assertEqual(result.source, "openai")

    def test_openai_timer_intent(self):
        engine = self._get_engine_with_mock({
            "intent": "set_timer",
            "entities": {"duration_minutes": 10},
            "confidence": 0.98,
        })
        result = engine._extract_openai("Set a timer for 10 minutes", [])
        self.assertIsNotNone(result)
        self.assertEqual(result.intent, "set_timer")
        self.assertEqual(result.entities["duration_minutes"], 10)

    def test_openai_fallback_on_error(self):
        """When OpenAI raises an exception, _extract_openai should return None."""
        with patch("assistant.intent_engine.settings") as mock_settings:
            mock_settings.openai_available = True
            mock_settings.openai_api_key = "sk-fake"
            mock_settings.openai_model = "gpt-4o-mini"
            mock_settings.openai_timeout = 10
            with patch("assistant.intent_engine.IntentEngine.__init__", return_value=None):
                from assistant.intent_engine import IntentEngine
                engine = IntentEngine.__new__(IntentEngine)
                engine._openai_client = MagicMock()
                engine._openai_client.chat.completions.create.side_effect = Exception("API error")
                engine._regex_rules = []

        result = engine._extract_openai("some text", [])
        self.assertIsNone(result)


class TestWakeWordDetector(unittest.TestCase):

    def setUp(self):
        from assistant.wakeword import WakeWordDetector
        self.detector = WakeWordDetector(wake_word="nova", sensitivity=0.5, enabled=True)

    def test_exact_match(self):
        self.assertTrue(self.detector.is_wake_word("Hey Nova how are you?"))

    def test_alias_match(self):
        self.assertTrue(self.detector.is_wake_word("okay nova what time is it"))

    def test_no_match(self):
        self.assertFalse(self.detector.is_wake_word("hello there general kenobi"))

    def test_disabled_always_false(self):
        self.detector.disable()
        self.assertFalse(self.detector.is_wake_word("nova"))

    def test_enable_re_enables(self):
        self.detector.disable()
        self.detector.enable()
        self.assertTrue(self.detector.is_wake_word("nova"))

    def test_strip_wake_word(self):
        result = self.detector.strip_wake_word("Nova, what's the weather?")
        self.assertNotIn("Nova", result.lower())
        self.assertIn("weather", result.lower())

    def test_empty_string(self):
        self.assertFalse(self.detector.is_wake_word(""))

    def test_case_insensitive(self):
        self.assertTrue(self.detector.is_wake_word("NOVA can you help me"))

    def test_set_wake_word(self):
        self.detector.set_wake_word("jarvis")
        self.assertTrue(self.detector.is_wake_word("hey jarvis open chrome"))
        self.assertFalse(self.detector.is_wake_word("nova what time is it"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
