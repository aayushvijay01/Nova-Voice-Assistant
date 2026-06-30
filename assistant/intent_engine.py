"""
assistant/intent_engine.py
==========================
Natural language understanding / intent extraction for Nova Voice Assistant.

Primary:  OpenAI function calling (gpt-4o-mini or configured model)
Fallback: Regex-based rule engine (works fully offline)

Returns a structured ``IntentResult`` containing:
- intent label (e.g. "get_weather", "set_timer")
- entities dict (e.g. {"city": "London", "duration_minutes": 10})
- raw user text

Usage
-----
    engine = IntentEngine()
    result = engine.extract("What's the weather in London?")
    print(result.intent, result.entities)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.settings import settings
from utils.logger import get_logger
from utils.helpers import extract_number, parse_time_expression

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class IntentResult:
    """Structured result from intent extraction."""
    intent: str                                 # snake_case intent label
    entities: Dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 1.0
    source: str = "openai"                      # "openai" | "regex"


# ---------------------------------------------------------------------------
# OpenAI function schema for intent extraction
# ---------------------------------------------------------------------------

_INTENT_FUNCTIONS: List[dict] = [
    {
        "type": "function",
        "function": {
            "name": "extract_intent",
            "description": (
                "Extract the user's intent and entities from a voice command. "
                "Return one of the defined intent labels."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": [
                            "get_weather",
                            "get_news",
                            "set_timer",
                            "calculate",
                            "set_reminder",
                            "system_control",
                            "web_search",
                            "open_application",
                            "get_time",
                            "get_date",
                            "chitchat",
                            "stop_listening",
                            "unknown",
                        ],
                        "description": "The detected intent label.",
                    },
                    "entities": {
                        "type": "object",
                        "description": (
                            "Key-value pairs of extracted entities. "
                            "E.g. city, duration_minutes, expression, query, app_name, message, time."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0–1.0.",
                    },
                },
                "required": ["intent", "entities"],
            },
        },
    }
]

_SYSTEM_PROMPT = (
    "You are Nova, an AI voice assistant. Your job is to extract the user's intent "
    "and relevant entities from voice commands. Always call extract_intent. "
    "Be concise with entity values. For duration, return integer minutes. "
    "For time expressions, return ISO-8601 if possible."
)


# ---------------------------------------------------------------------------
# Regex fallback rules
# ---------------------------------------------------------------------------

_REGEX_RULES: List[tuple[re.Pattern, str, Callable]] = []

def _make_rules():
    """Build and return regex rule list (called once on first use)."""
    rules = [
        # Weather
        (re.compile(r"\b(weather|temperature|forecast|hot|cold|rain|sunny)\b", re.I),
         "get_weather",
         lambda m, text: {"city": _extract_city(text)}),

        # News
        (re.compile(r"\b(news|headline|headlines|latest|top stories)\b", re.I),
         "get_news",
         lambda m, text: {}),

        # Timer
        (re.compile(r"\b(timer|set.*timer|timer.*for)\b", re.I),
         "set_timer",
         lambda m, text: {"duration_minutes": int(extract_number(text) or 1)}),

        # Calculator
        (re.compile(r"\b(calculate|what is|compute|how much is|equals?)\b.*[\d\+\-\*\/]", re.I),
         "calculate",
         lambda m, text: {"expression": text}),

        # Reminder
        (re.compile(r"\b(remind|reminder|remember to|don.t forget)\b", re.I),
         "set_reminder",
         lambda m, text: {"message": text, "time": None}),

        # Time
        (re.compile(r"\bwhat.?s? (the )?time\b|what time is it\b", re.I),
         "get_time",
         lambda m, text: {}),

        # Date
        (re.compile(r"\bwhat.?s? (the )?date\b|what day is (it|today)\b", re.I),
         "get_date",
         lambda m, text: {}),

        # System: open app
        (re.compile(r"\b(open|launch|start)\s+(\w[\w\s]*)", re.I),
         "open_application",
         lambda m, text: {"app_name": m.group(2).strip()}),

        # System control
        (re.compile(r"\b(shutdown|restart|reboot|lock|sleep|volume|mute|unmute)\b", re.I),
         "system_control",
         lambda m, text: {"action": m.group(1).lower()}),

        # Web search
        (re.compile(r"\b(search|google|look up|find|browse)\b", re.I),
         "web_search",
         lambda m, text: {"query": re.sub(r".*?(search|google|look up|find|browse)\s*(for\s*)?", "", text, flags=re.I).strip()}),

        # Stop
        (re.compile(r"\b(stop|quit|exit|goodbye|bye|shut up)\b", re.I),
         "stop_listening",
         lambda m, text: {}),
    ]
    return rules


from typing import Callable  # noqa: E402 (needed before _make_rules)


def _extract_city(text: str) -> str:
    """Heuristically extract a city name from weather utterances."""
    patterns = [
        r"(?:weather|forecast|temperature)\s+(?:in|at|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        r"(?:in|at|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return settings.default_city


# ---------------------------------------------------------------------------
# Intent Engine
# ---------------------------------------------------------------------------

class IntentEngine:
    """
    Dual-mode intent extraction engine.

    Uses OpenAI function calling when an API key is available, otherwise
    falls back to regex rules for fully offline operation.
    """

    def __init__(self) -> None:
        self._openai_client = None
        self._regex_rules = _make_rules()

        if settings.openai_available:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=settings.openai_api_key,
                    timeout=settings.openai_timeout,
                )
                logger.info("IntentEngine: OpenAI client initialised (model=%s)", settings.openai_model)
            except Exception as exc:
                logger.error("Failed to create OpenAI client: %s", exc)

        if not self._openai_client:
            logger.info("IntentEngine: running in offline regex mode")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, text: str, context: Optional[List[dict]] = None) -> IntentResult:
        """
        Extract intent and entities from user utterance.

        Parameters
        ----------
        text:       Transcribed user utterance (wake word already stripped).
        context:    Optional list of prior conversation turns for context.

        Returns
        -------
        IntentResult with intent label and entities dict.
        """
        if not text or not text.strip():
            return IntentResult(intent="unknown", raw_text="")

        text = text.strip()

        if self._openai_client:
            result = self._extract_openai(text, context or [])
            if result:
                return result

        # Fallback: regex
        return self._extract_regex(text)

    # ------------------------------------------------------------------
    # OpenAI path
    # ------------------------------------------------------------------

    def _extract_openai(
        self,
        text: str,
        context: List[dict],
    ) -> Optional[IntentResult]:
        """Use OpenAI function calling to extract intent."""
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        # Add up to 4 recent turns for context
        messages.extend(context[-4:] if len(context) > 4 else context)
        messages.append({"role": "user", "content": text})

        try:
            response = self._openai_client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                tools=_INTENT_FUNCTIONS,
                tool_choice={"type": "function", "function": {"name": "extract_intent"}},
                temperature=0.1,
                max_tokens=256,
            )
            tool_call = response.choices[0].message.tool_calls[0]
            args = json.loads(tool_call.function.arguments)
            return IntentResult(
                intent=args.get("intent", "unknown"),
                entities=args.get("entities", {}),
                raw_text=text,
                confidence=float(args.get("confidence", 0.9)),
                source="openai",
            )
        except Exception as exc:
            logger.warning("OpenAI intent extraction failed: %s — using regex", exc)
            return None

    # ------------------------------------------------------------------
    # Regex fallback
    # ------------------------------------------------------------------

    def _extract_regex(self, text: str) -> IntentResult:
        """Rule-based intent extraction (fully offline)."""
        for pattern, intent, entity_fn in self._regex_rules:
            m = pattern.search(text)
            if m:
                try:
                    entities = entity_fn(m, text)
                except Exception:
                    entities = {}
                logger.debug("Regex intent: %s | entities: %s", intent, entities)
                return IntentResult(
                    intent=intent,
                    entities=entities,
                    raw_text=text,
                    confidence=0.75,
                    source="regex",
                )
        # Default: chitchat / general
        return IntentResult(
            intent="chitchat",
            entities={"query": text},
            raw_text=text,
            confidence=0.5,
            source="regex",
        )
