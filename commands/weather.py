"""
commands/weather.py
===================
Weather command handler for Nova Voice Assistant.

Uses the OpenWeatherMap API (free tier) to fetch current weather conditions.
Falls back to a graceful error message when offline or no API key.

Handler
-------
    handle(entities: dict) -> str
    entities keys: city (str, optional)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from config.settings import settings
from utils.logger import get_logger
from utils.helpers import retry

logger = get_logger(__name__)

# OpenWeatherMap condition code ranges → emoji + description
_CONDITION_MAP = {
    (200, 299): ("⛈", "thunderstorm"),
    (300, 399): ("🌧", "drizzle"),
    (500, 599): ("🌧", "rain"),
    (600, 699): ("❄", "snow"),
    (700, 799): ("🌫", "mist"),
    (800, 800): ("☀", "clear sky"),
    (801, 804): ("🌥", "cloudy"),
}


def _condition_label(code: int) -> str:
    for (low, high), (_, label) in _CONDITION_MAP.items():
        if low <= code <= high:
            return label
    return "unknown"


@retry(max_attempts=2, delay=1.0, exceptions=(requests.RequestException,))
def _fetch_weather(city: str, api_key: str) -> dict:
    """Perform the OpenWeatherMap API call."""
    url = f"{settings.openweather_base_url}/weather"
    params = {
        "q": city,
        "appid": api_key,
        "units": "metric",
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def handle(entities: Dict[str, Any]) -> str:
    """
    Fetch and narrate current weather conditions.

    Parameters
    ----------
    entities:   May contain 'city' key.

    Returns
    -------
    Human-readable weather description.
    """
    if not settings.weather_available:
        return (
            "I don't have a weather API key configured. "
            "Please add your OpenWeatherMap key to the .env file."
        )

    city: str = entities.get("city") or settings.default_city
    city = city.strip().title()

    logger.info("Weather command: fetching for city=%r", city)

    try:
        data = _fetch_weather(city, settings.openweather_api_key)

        temp_c = round(data["main"]["temp"])
        feels_like = round(data["main"]["feels_like"])
        humidity = data["main"]["humidity"]
        condition_code = data["weather"][0]["id"]
        description = data["weather"][0]["description"].capitalize()
        wind_speed = round(data["wind"]["speed"] * 3.6)  # m/s → km/h

        condition = _condition_label(condition_code)

        return (
            f"The current weather in {city} is {description}. "
            f"Temperature is {temp_c} degrees Celsius, "
            f"feels like {feels_like} degrees. "
            f"Humidity is {humidity} percent and wind speed is {wind_speed} kilometres per hour."
        )

    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return f"I couldn't find weather data for {city}. Please check the city name."
        logger.error("Weather API HTTP error: %s", exc)
        return "I had trouble reaching the weather service. Please try again."
    except requests.RequestException as exc:
        logger.error("Weather request error: %s", exc)
        return "I couldn't connect to the weather service. Please check your internet connection."
    except Exception as exc:
        logger.error("Unexpected weather error: %s", exc)
        return "Something went wrong while fetching the weather. Please try again."
