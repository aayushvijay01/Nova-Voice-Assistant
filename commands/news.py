"""
commands/news.py
================
News headlines command handler for Nova Voice Assistant.

Uses NewsAPI.org (free tier) to fetch today's top headlines.
Gracefully degrades when offline or no API key is configured.

Handler
-------
    handle(entities: dict) -> str
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from config.settings import settings
from utils.logger import get_logger
from utils.helpers import retry

logger = get_logger(__name__)

MAX_HEADLINES = 5


@retry(max_attempts=2, delay=1.0, exceptions=(requests.RequestException,))
def _fetch_headlines(api_key: str, country: str = "us", page_size: int = MAX_HEADLINES) -> List[dict]:
    """Call the NewsAPI top-headlines endpoint."""
    url = f"{settings.news_api_base_url}/top-headlines"
    params = {
        "apiKey": api_key,
        "country": country,
        "pageSize": page_size,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data.get("articles", [])


def handle(entities: Dict[str, Any]) -> str:
    """
    Fetch and narrate the top news headlines.

    Parameters
    ----------
    entities:   May contain 'category' or 'country' keys.

    Returns
    -------
    Narrated news summary string.
    """
    if not settings.news_available:
        return (
            "I don't have a news API key configured. "
            "Please add your NewsAPI key to the .env file."
        )

    country: str = entities.get("country", "us")

    logger.info("News command: fetching top headlines (country=%s)", country)

    try:
        articles = _fetch_headlines(settings.news_api_key, country=country)

        if not articles:
            return "I couldn't find any news headlines right now. Please try again later."

        # Build spoken response
        lines = [f"Here are the top {len(articles)} headlines."]
        for i, article in enumerate(articles, start=1):
            title = article.get("title", "").split(" - ")[0].strip()
            if title and title != "[Removed]":
                lines.append(f"Headline {i}: {title}.")

        lines.append("Those are today's top stories.")
        return " ".join(lines)

    except requests.HTTPError as exc:
        logger.error("News API HTTP error: %s", exc)
        return "I had trouble reaching the news service. Please try again."
    except requests.RequestException as exc:
        logger.error("News request error: %s", exc)
        return "I couldn't connect to the news service. Please check your internet connection."
    except Exception as exc:
        logger.error("Unexpected news error: %s", exc)
        return "Something went wrong while fetching the news. Please try again."
