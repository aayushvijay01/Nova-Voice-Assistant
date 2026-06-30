"""
assistant/response_generator.py
================================
Natural language response generation for Nova Voice Assistant.

Primary:  OpenAI streaming chat completions
Fallback: Template-based responses (fully offline)

The generator maintains a short conversation history in memory (backed by
the database) to support multi-turn contextual conversations.

Usage
-----
    gen = ResponseGenerator()
    for chunk in gen.stream("Tell me a joke"):
        print(chunk, end="", flush=True)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Generator, List, Optional

from config.settings import settings
from utils.logger import get_logger
from utils.helpers import human_time, human_date

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_NOVA_SYSTEM_PROMPT = """You are Nova, a friendly, knowledgeable, and concise desktop AI voice assistant.

Guidelines:
- Keep responses conversational and natural — suitable for text-to-speech.
- Be concise (2–4 sentences unless asked for detail).
- Do not use markdown, bullet points, code blocks, or emoji in responses.
- Speak in first person as Nova.
- If you don't know something, say so honestly.
- Today's date is {date}. Current time is {time}.
"""

# ---------------------------------------------------------------------------
# Offline template responses
# ---------------------------------------------------------------------------

_OFFLINE_TEMPLATES: dict[str, str] = {
    "get_time": "The current time is {time}.",
    "get_date": "Today is {date}.",
    "chitchat": "I'm Nova, your voice assistant. How can I help you today?",
    "unknown": "I'm not sure how to help with that. Could you rephrase?",
    "stop_listening": "Goodbye! I'll be here whenever you need me.",
    "calculate": "Let me calculate that for you.",
    "get_weather": "I need an internet connection and a weather API key to check the weather.",
    "get_news": "I need an internet connection and a news API key to fetch headlines.",
}


class ResponseGenerator:
    """
    Generates natural language responses using OpenAI or offline templates.

    Supports streaming output for real-time display and low latency TTS.
    """

    def __init__(self) -> None:
        self._openai_client = None
        self._conversation_history: List[dict] = []

        if settings.openai_available:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=settings.openai_api_key,
                    timeout=settings.openai_timeout,
                )
                logger.info("ResponseGenerator: OpenAI client ready")
            except Exception as exc:
                logger.error("ResponseGenerator: OpenAI init failed: %s", exc)

        if not self._openai_client:
            logger.info("ResponseGenerator: offline template mode active")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str, context: Optional[List[dict]] = None) -> str:
        """
        Generate a complete response string (non-streaming).

        Parameters
        ----------
        prompt:     The user's message or command result to respond to.
        context:    Optional prior conversation turns.

        Returns
        -------
        Full response string.
        """
        return "".join(self.stream(prompt, context))

    def stream(
        self,
        prompt: str,
        context: Optional[List[dict]] = None,
        intent: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Stream response tokens as a generator.

        Each yielded value is a text chunk (may be a word or partial sentence).
        Suitable for real-time display and chunked TTS delivery.

        Parameters
        ----------
        prompt:     User message.
        context:    Prior conversation history in OpenAI message format.
        intent:     Detected intent for offline template selection.
        """
        if not prompt.strip():
            return

        if self._openai_client:
            yield from self._stream_openai(prompt, context or [])
        else:
            yield self._offline_response(prompt, intent)

    def add_to_history(self, role: str, content: str) -> None:
        """Append a turn to the in-memory conversation history."""
        self._conversation_history.append({"role": role, "content": content})
        # Keep last N turns to limit token usage
        max_turns = 20
        if len(self._conversation_history) > max_turns:
            # Always keep the system prompt removed, just trim oldest turns
            self._conversation_history = self._conversation_history[-max_turns:]

    def clear_history(self) -> None:
        """Wipe in-memory conversation history."""
        self._conversation_history.clear()

    def set_context_from_db(self, db_context: List[dict]) -> None:
        """Seed in-memory history from database records."""
        self._conversation_history = db_context[-20:]

    # ------------------------------------------------------------------
    # OpenAI streaming
    # ------------------------------------------------------------------

    def _stream_openai(
        self,
        prompt: str,
        extra_context: List[dict],
    ) -> Generator[str, None, None]:
        """Stream tokens from OpenAI chat completion API."""
        now = datetime.now()
        system_msg = {
            "role": "system",
            "content": _NOVA_SYSTEM_PROMPT.format(
                date=human_date(now),
                time=human_time(now),
            ),
        }

        # Merge DB context + in-memory history, deduplicate by recency
        messages = [system_msg]
        combined = (extra_context + self._conversation_history)[-18:]
        messages.extend(combined)
        messages.append({"role": "user", "content": prompt})

        try:
            with self._openai_client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=settings.openai_temperature,
                max_tokens=settings.openai_max_tokens,
                stream=True,
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content
        except Exception as exc:
            logger.error("OpenAI streaming error: %s", exc)
            yield self._offline_response(prompt, None)

    # ------------------------------------------------------------------
    # Offline template
    # ------------------------------------------------------------------

    def _offline_response(self, prompt: str, intent: Optional[str]) -> str:
        """Return a template-based response for offline operation."""
        now = datetime.now()
        ctx = {
            "time": human_time(now),
            "date": human_date(now),
            "query": prompt,
        }
        template = _OFFLINE_TEMPLATES.get(intent or "chitchat", _OFFLINE_TEMPLATES["unknown"])
        try:
            return template.format(**ctx)
        except KeyError:
            return template
