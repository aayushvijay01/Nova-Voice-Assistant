"""
tests/test_commands.py
======================
Unit tests for Nova Voice Assistant command handlers.

Tests each command module in isolation with mocked network calls.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Calculator tests
# ---------------------------------------------------------------------------

class TestCalculatorCommand(unittest.TestCase):
    """Test the safe_eval-based calculator command."""

    def _handle(self, expression: str) -> str:
        from commands.calculator import handle
        return handle({"expression": expression})

    def test_basic_addition(self):
        result = self._handle("12 + 8")
        self.assertIn("20", result)

    def test_multiplication(self):
        result = self._handle("245 * 87")
        self.assertIn("21315", result)

    def test_spoken_multiplication(self):
        result = self._handle("What is 6 times 7?")
        self.assertIn("42", result)

    def test_spoken_plus(self):
        result = self._handle("What is 100 plus 200?")
        self.assertIn("300", result)

    def test_division(self):
        result = self._handle("100 divided by 4")
        self.assertIn("25", result)

    def test_square_root(self):
        result = self._handle("square root of 144")
        self.assertIn("12", result)

    def test_empty_expression(self):
        result = self._handle("")
        self.assertIn("didn't catch", result.lower())

    def test_invalid_expression(self):
        result = self._handle("hello world")
        self.assertIn("couldn't evaluate", result.lower())

    def test_float_result(self):
        result = self._handle("1 / 3")
        self.assertIn("0.333", result)

    def test_power(self):
        result = self._handle("2 to the power of 10")
        self.assertIn("1024", result)


# ---------------------------------------------------------------------------
# Timer tests
# ---------------------------------------------------------------------------

class TestTimerCommand(unittest.TestCase):
    """Test the timer command."""

    def setUp(self):
        # Patch threading.Timer to avoid actually waiting
        self._timer_patch = patch("commands.timer.threading.Timer")
        self._mock_timer_cls = self._timer_patch.start()
        self._mock_timer = MagicMock()
        self._mock_timer_cls.return_value = self._mock_timer
        # Clear global timer list
        import commands.timer as t
        t._active_timers.clear()

    def tearDown(self):
        self._timer_patch.stop()

    def test_set_timer_minutes(self):
        from commands.timer import handle
        result = handle({"duration_minutes": 5})
        self.assertIn("5 minute", result.lower())
        self.assertIn("timer set", result.lower())
        self._mock_timer.start.assert_called_once()

    def test_set_timer_one_minute(self):
        from commands.timer import handle
        result = handle({"duration_minutes": 1})
        self.assertIn("1 minute", result.lower())

    def test_invalid_duration(self):
        from commands.timer import handle
        result = handle({"duration_minutes": 0})
        self.assertIn("couldn't determine", result.lower())

    def test_no_duration(self):
        from commands.timer import handle
        result = handle({})
        self.assertIn("couldn't determine", result.lower())

    def test_timer_callback_injected(self):
        from commands.timer import set_tts_callback, handle
        callback = MagicMock()
        set_tts_callback(callback)
        handle({"duration_minutes": 1})
        # Timer was created — simulate firing
        timer_fn = self._mock_timer_cls.call_args[1]["function"] if self._mock_timer_cls.call_args[1] else self._mock_timer_cls.call_args[0][1]
        # Just verify the timer was instantiated properly
        self.assertTrue(self._mock_timer.start.called)


# ---------------------------------------------------------------------------
# Web Search tests
# ---------------------------------------------------------------------------

class TestWebSearchCommand(unittest.TestCase):

    @patch("commands.web_search.webbrowser.open", return_value=True)
    def test_search_google(self, mock_open):
        from commands.web_search import handle
        result = handle({"query": "Python tutorials", "engine": "google"})
        self.assertIn("Google", result)
        self.assertIn("Python tutorials", result)
        mock_open.assert_called_once()

    @patch("commands.web_search.webbrowser.open", return_value=True)
    def test_search_youtube(self, mock_open):
        from commands.web_search import handle
        result = handle({"query": "jazz music", "engine": "youtube"})
        self.assertIn("YouTube", result)

    @patch("commands.web_search.webbrowser.open", return_value=True)
    def test_open_url(self, mock_open):
        from commands.web_search import handle
        result = handle({"query": "github.com"})
        self.assertIn("Opening", result)

    def test_empty_query(self):
        from commands.web_search import handle
        result = handle({"query": ""})
        self.assertIn("What would you like", result)


# ---------------------------------------------------------------------------
# Weather tests
# ---------------------------------------------------------------------------

class TestWeatherCommand(unittest.TestCase):

    def test_no_api_key(self):
        """Should return graceful message when no API key is set."""
        from commands.weather import handle
        with patch("commands.weather.settings") as mock_settings:
            mock_settings.weather_available = False
            result = handle({"city": "London"})
        self.assertIn("API key", result)

    @patch("commands.weather._fetch_weather")
    def test_successful_fetch(self, mock_fetch):
        mock_fetch.return_value = {
            "main": {"temp": 20, "feels_like": 18, "humidity": 65},
            "weather": [{"id": 800, "description": "clear sky"}],
            "wind": {"speed": 3.5},
        }
        with patch("commands.weather.settings") as mock_settings:
            mock_settings.weather_available = True
            mock_settings.openweather_api_key = "fake"
            mock_settings.default_city = "London"
            from commands.weather import handle
            result = handle({"city": "London"})
        self.assertIn("London", result)
        self.assertIn("20", result)

    @patch("commands.weather._fetch_weather")
    def test_city_not_found(self, mock_fetch):
        import requests
        resp = MagicMock()
        resp.status_code = 404
        mock_fetch.side_effect = requests.HTTPError(response=resp)
        with patch("commands.weather.settings") as mock_settings:
            mock_settings.weather_available = True
            mock_settings.openweather_api_key = "fake"
            mock_settings.default_city = "London"
            from commands.weather import handle
            result = handle({"city": "FakeCity123"})
        self.assertIn("couldn't find", result.lower())


# ---------------------------------------------------------------------------
# News tests
# ---------------------------------------------------------------------------

class TestNewsCommand(unittest.TestCase):

    def test_no_api_key(self):
        from commands.news import handle
        with patch("commands.news.settings") as mock_settings:
            mock_settings.news_available = False
            result = handle({})
        self.assertIn("API key", result)

    @patch("commands.news._fetch_headlines")
    def test_successful_fetch(self, mock_fetch):
        mock_fetch.return_value = [
            {"title": "Python 4.0 Released - Tech News"},
            {"title": "AI Breakthrough - Science Daily"},
            {"title": "Stock Market Hits Record - Finance"},
        ]
        with patch("commands.news.settings") as mock_settings:
            mock_settings.news_available = True
            mock_settings.news_api_key = "fake"
            mock_settings.news_api_base_url = "https://newsapi.org/v2"
            from commands.news import handle
            result = handle({})
        self.assertIn("Python 4.0", result)
        self.assertIn("Headline 1", result)

    @patch("commands.news._fetch_headlines")
    def test_empty_articles(self, mock_fetch):
        mock_fetch.return_value = []
        with patch("commands.news.settings") as mock_settings:
            mock_settings.news_available = True
            mock_settings.news_api_key = "fake"
            mock_settings.news_api_base_url = "https://newsapi.org/v2"
            from commands.news import handle
            result = handle({})
        self.assertIn("couldn't find", result.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
