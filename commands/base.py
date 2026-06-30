"""
commands/base.py
================
Abstract base class for all Nova Voice Assistant commands.

Every command module must expose a ``handle(entities: dict) -> str`` function
(and optionally ``handle_open``, ``handle_start``, etc. for multi-intent modules).

The BaseCommand ABC is provided for object-oriented plugin implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CommandMetadata:
    """Metadata descriptor for a command plugin."""
    name: str
    description: str
    intent: str
    aliases: List[str] = field(default_factory=list)
    requires_internet: bool = False
    requires_api_key: bool = False
    examples: List[str] = field(default_factory=list)


class BaseCommand(ABC):
    """
    Abstract base class for Nova command plugins.

    Subclass this to create new commands as classes rather than standalone
    functions.  The executor will call ``execute(entities)`` automatically
    when the command is registered.

    Example
    -------
        class MyCommand(BaseCommand):
            @property
            def metadata(self):
                return CommandMetadata(name="my_command", ...)

            def execute(self, entities):
                return "Done!"
    """

    @property
    @abstractmethod
    def metadata(self) -> CommandMetadata:
        """Return the command's metadata descriptor."""
        ...

    @abstractmethod
    def execute(self, entities: Dict[str, Any]) -> str:
        """
        Execute the command and return a TTS-ready response string.

        Parameters
        ----------
        entities:   Extracted entities from IntentEngine.

        Returns
        -------
        Human-readable plain-text response.
        """
        ...

    def __call__(self, entities: Dict[str, Any]) -> str:
        """Allow instances to be used directly as command handlers."""
        return self.execute(entities)
