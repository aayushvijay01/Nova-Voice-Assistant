"""
commands/web_search.py
======================
Web search and URL opening command for Nova Voice Assistant.

Handlers
--------
    handle(entities: dict) -> str   # web_search intent
"""

from __future__ import annotations

import re
import urllib.parse
import webbrowser
from typing import Any, Dict

from utils.logger import get_logger

logger = get_logger(__name__)

# Known URL patterns → open directly
_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?([a-zA-Z0-9\-]+)\.(com|org|net|io|co|gov|edu|ai)(?:/\S*)?",
    re.IGNORECASE,
)

_SEARCH_ENGINE_URL = "https://www.google.com/search?q={query}"
_YOUTUBE_URL = "https://www.youtube.com/results?search_query={query}"


def handle(entities: Dict[str, Any]) -> str:
    """
    Perform a web search or open a URL.

    Parameters
    ----------
    entities:
        query   — The search query or URL.
        engine  — 'google' (default) | 'youtube'.

    Returns
    -------
    Confirmation string.
    """
    query: str = entities.get("query", "") or entities.get("raw_text", "")
    engine: str = entities.get("engine", "google").lower()

    if not query:
        return "What would you like me to search for?"

    query = query.strip()
    logger.info("Web search: query=%r engine=%s", query[:80], engine)

    # Check if it looks like a direct URL
    if _URL_PATTERN.search(query):
        url = query if query.startswith("http") else f"https://{query}"
        try:
            webbrowser.open(url)
            domain = urllib.parse.urlparse(url).netloc or url
            return f"Opening {domain} in your browser."
        except Exception as exc:
            logger.error("Failed to open URL %r: %s", url, exc)
            return f"I couldn't open that website: {exc}"

    # Build search URL
    encoded_query = urllib.parse.quote_plus(query)
    if engine == "youtube":
        url = _YOUTUBE_URL.format(query=encoded_query)
        site_name = "YouTube"
    else:
        url = _SEARCH_ENGINE_URL.format(query=encoded_query)
        site_name = "Google"

    try:
        webbrowser.open(url)
        return f"Searching {site_name} for: {query}."
    except Exception as exc:
        logger.error("Failed to open search: %s", exc)
        return f"I couldn't open the browser: {exc}"
