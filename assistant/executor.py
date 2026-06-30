"""
assistant/executor.py
=====================
Command dispatcher / router for Nova Voice Assistant.

The executor maintains a registry of command handlers keyed by intent label.
It routes an ``IntentResult`` to the appropriate handler, calls it, and
returns a plain-text result string ready for TTS/display.

Plugin-style registration allows new commands to be added without modifying
this module.

Usage
-----
    executor = CommandExecutor()
    result = executor.execute(intent_result)
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from assistant.intent_engine import IntentResult
from utils.logger import get_logger

logger = get_logger(__name__)

# Type alias for a command handler function
CommandHandler = Callable[[Dict], str]


class CommandExecutor:
    """
    Intent → command dispatcher with a plugin-friendly registry.

    Command handlers are functions with signature:
        def handler(entities: dict) -> str

    Handlers should return a human-readable response string (spoken to user).
    """

    def __init__(self) -> None:
        self._registry: Dict[str, CommandHandler] = {}
        self._register_builtin_commands()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, intent: str, handler: CommandHandler) -> None:
        """
        Register a handler for an intent label.

        Parameters
        ----------
        intent:     Snake-case intent string (e.g. "get_weather").
        handler:    Callable accepting an entities dict, returning str.
        """
        self._registry[intent.lower()] = handler
        logger.debug("CommandExecutor: registered handler for intent '%s'", intent)

    def execute(self, intent_result: IntentResult) -> str:
        """
        Dispatch an IntentResult to its registered handler.

        Parameters
        ----------
        intent_result:  Structured output from IntentEngine.

        Returns
        -------
        Human-readable response string (or error message).
        """
        intent = intent_result.intent.lower()
        entities = intent_result.entities
        raw_text = intent_result.raw_text

        handler = self._registry.get(intent)
        if handler is None:
            logger.debug("No handler for intent '%s' — falling back to chitchat", intent)
            handler = self._registry.get("chitchat")

        if handler is None:
            return "I'm not sure how to help with that."

        try:
            logger.info("Executing command: intent=%s entities=%s", intent, entities)
            result = handler(entities)
            return result if isinstance(result, str) else str(result)
        except Exception as exc:
            logger.error("Command execution error [%s]: %s", intent, exc, exc_info=True)
            return f"I encountered an error while handling that request: {exc}"

    def list_commands(self) -> list[str]:
        """Return a sorted list of all registered intent names."""
        return sorted(self._registry.keys())

    # ------------------------------------------------------------------
    # Built-in command registration
    # ------------------------------------------------------------------

    def _register_builtin_commands(self) -> None:
        """Import and register all built-in command modules."""
        # Each import registers the handler; errors are non-fatal
        self._safe_register_module("commands.weather", "get_weather", "handle")
        self._safe_register_module("commands.news", "get_news", "handle")
        self._safe_register_module("commands.timer", "set_timer", "handle")
        self._safe_register_module("commands.calculator", "calculate", "handle")
        self._safe_register_module("commands.reminder", "set_reminder", "handle")
        self._safe_register_module("commands.system_control", "system_control", "handle")
        self._safe_register_module("commands.system_control", "open_application", "handle_open")
        self._safe_register_module("commands.web_search", "web_search", "handle")

        # Inline lightweight handlers for time/date/chitchat
        self._register_time_date_handlers()

    def _safe_register_module(
        self,
        module_path: str,
        intent: str,
        fn_name: str,
    ) -> None:
        """Import a module and register its handler function."""
        try:
            import importlib
            mod = importlib.import_module(module_path)
            handler = getattr(mod, fn_name)
            self.register(intent, handler)
        except Exception as exc:
            logger.warning(
                "Could not register handler %s.%s for intent '%s': %s",
                module_path, fn_name, intent, exc,
            )

    def _register_time_date_handlers(self) -> None:
        """Register lightweight time/date/stop handlers inline."""
        from datetime import datetime
        from utils.helpers import human_time, human_date

        def get_time(entities: dict) -> str:
            return f"The current time is {human_time(datetime.now())}."

        def get_date(entities: dict) -> str:
            return f"Today is {human_date(datetime.now())}."

        def stop_listening(entities: dict) -> str:
            return "Goodbye! Call me whenever you need help."

        def chitchat(entities: dict) -> str:
            return "I'm here to help. You can ask me about the weather, news, set timers, or just chat."

        self.register("get_time", get_time)
        self.register("get_date", get_date)
        self.register("stop_listening", stop_listening)
        self.register("chitchat", chitchat)
        self.register("unknown", chitchat)
